#!/usr/bin/env python3

import json
import os
import re
import requests
import subprocess
from gquery import gquery
from urllib.parse import urlparse
from shutil import rmtree
from packaging.version import Version, InvalidVersion

REPO_DIR = "fdroid/repo"
ICON_DIR_PATTERN = re.compile(r"(?:icons|icons-\d+)")

def main():
  with open("apks.json") as file:
    apks = json.load(file)
  tombstones = load_tombstones()
  if os.path.isfile("versioncache.json"):
    with open("versioncache.json") as file:
      versioncache = json.load(file)
    if "format" not in versioncache or versioncache["format"] != 2:
      print("Found outdated version cache, creating new")
      versioncache = {"format": 2, "apps": {}, "volatile_paths": []}
      rmtree("fdroid/repo")
    else:
      print("Found version cache, using")
  else:
    print("Version cache not found, creating")
    versioncache = {"format": 2, "apps": {}, "volatile_paths": []}
  if not "volatile_paths" in versioncache:
    versioncache["volatile_paths"] = []
  remove_all(versioncache["volatile_paths"])
  versioncache["volatile_paths"] = []
  os.makedirs(REPO_DIR, exist_ok=True)
  remove_tombstones(tombstones)
  prune_stale_icons()
  apps_cache = versioncache["apps"]
  known_paths = set()
  for apk in apks:
    fmt={}
    forceFileName = None
    ignore = False
    if "version" in apk:
      fmt["ver"] = str(resolve_template_value(apk["version"], "version"))
      fmt["ver_stripped"] = fmt["ver"].lstrip("v")
      fmt["ver_splitted"] = fmt["ver"].split(".")
      if apk["name"] in apps_cache:
        if apps_cache[apk["name"]]["version"] != fmt["ver"]:
          print("Updating " + apk["name"] + ": new version is available")
          remove_all(apps_cache[apk["name"]]["paths"])
          apps_cache[apk["name"]] = {"version": fmt["ver"], "paths": []}
        elif len(apps_cache[apk["name"]]["paths"]) != (len(apk["architectures"]) if "architectures" in apk else 1):
          print("Redownloading " + apk["name"] + ": mistmatch in architecture count")
          remove_all(apps_cache[apk["name"]]["paths"])
          apps_cache[apk["name"]] = {"version": fmt["ver"], "paths": []}
        else:
          print("Skipping " + apk["name"] + ": already up to date")
          for path in apps_cache[apk["name"]]["paths"]:
            known_paths.add(path)
            if not os.path.isfile(path):
              print("Warning: missing file for application: " + path)
          continue
      else:
        print("Adding " + apk["name"] + ": new application")
        apps_cache[apk["name"]] = {"version": fmt["ver"], "paths": []}
      app_paths = apps_cache[apk["name"]]["paths"]
      print("Downloading " + apk["name"] + " " + fmt["ver"])
    else:
      app_paths = versioncache["volatile_paths"]
      print("Downloading " + apk["name"])
    if "sourceFileName" in apk:
      fmt["source_file_name"] = resolve_template_value(apk["sourceFileName"], "sourceFileName")
    if "forceFileName" in apk:
      forceFileName = apk["forceFileName"]
    if forceFileName is not None:
      fmt["arch"] = "{arch}"
      forceFileName = forceFileName.format_map(fmt)
      fmt["force_file_name"] = forceFileName
      del fmt["arch"]
    if "ignoreErrors" in apk:
      ignore = apk["ignoreErrors"]
    base_url = resolve_template_value(apk["baseUrl"], "baseUrl")
    if "architectures" in apk:
      for arch in apk["architectures"]:
        archForceFileName = None if forceFileName is None else forceFileName.format(arch=arch)
        fmt["arch"] = arch
        download(base_url.format_map(fmt), archForceFileName, ignore, app_paths)
    else:
      download(base_url.format_map(fmt), forceFileName, ignore, app_paths)
    known_paths.update(app_paths)
  warn_unknown_files(known_paths)
  print("Writing new version cache")
  with open("versioncache.json", 'w') as file:
    json.dump(versioncache, file)

def add_authentication(url, headers):
  parsed_url = urlparse(url)
  if parsed_url.netloc == "api.github.com":
    token = os.getenv("GITHUB_TOKEN")
    if token:
      headers["Authorization"] = f"Bearer {token}"

def resolve_template_value(value_spec, name):
  if isinstance(value_spec, dict):
    if "literal" in value_spec:
      return value_spec["literal"]
    if "json" in value_spec:
      return get_version_json(value_spec["url"], value_spec["json"])
    if "regex" in value_spec:
      return get_version_regex(value_spec["url"], value_spec["regex"])
    raise ValueError("Unsupported " + name + " configuration")
  return value_spec

def download(download_url, fileName, ignore, paths):
  try:
    headers = {}
    add_authentication(download_url, headers)
    response = requests.get(download_url, headers=headers, allow_redirects=True, stream=True)
    response.raise_for_status()
    if fileName is None:
      fileName = identify_file_name(download_url, response)
    fileName = REPO_DIR + "/" + fileName
    print("Using target file " + fileName)
    chunk_size = 8192
    with open(fileName, 'wb') as file:
      for chunk in response.iter_content(chunk_size):
        file.write(chunk)
    paths += [fileName]
  except Exception as e:
    if fileName is not None:
      # ensure we don't get empty leftover files
      try:
        os.unlink(fileName)
      except FileNotFoundError:
        # Not sure if this can happen, but if it does, it's OK.
        pass
    if not ignore:
      raise Exception("Failed downloading " + download_url)
    else:
      print("Ignoring error:")
      print(e)

def identify_file_name(download_url, response):
  if download_url.endswith(".apk"):
    return os.path.basename(urlparse(download_url).path)
  elif "Content-Disposition" in response.headers:
    match = re.search('filename="(.+)"', response.headers["Content-Disposition"])
    if match:
      return match.group(1)
    else:
      raise Exception("Could not get filename from content disposition of " + download_url)
  else:
    raise Exception("Could not get filename from " + download_url)

def get_version_regex(url, query):
  headers = {}
  add_authentication(url, headers)
  response = requests.get(url, headers=headers)
  response.raise_for_status()
  matches = [x.group(1) for x in re.finditer(query, response.text)]
  if not matches:
    raise ValueError("No matches found.")
  
  versioned_matches = []
  non_version_matches = []

  for match in matches:
      try:
          parsed_version = Version(match)
          versioned_matches.append((parsed_version, match))
      except InvalidVersion:
          non_version_matches.append(match)

  if versioned_matches:
    if non_version_matches:
      raise ValueError("Identified both valid and invalid versions. Adjust your regex!")
    highest_version = max(versioned_matches, key=lambda x: x[0])
    return highest_version[1]
  
  if len(non_version_matches) == 1:
      return non_version_matches[0]

  raise ValueError("Unable to determine a unique or highest version match.")

def get_version_json(url, query):
  headers = {}
  add_authentication(url, headers)
  response = requests.get(url, headers=headers)
  response.raise_for_status()
  return gquery(response.json(), query)

def remove_all(paths):
  for path in paths:
    if os.path.isfile(path):
      os.remove(path)
    if os.path.isdir(path):
      rmtree(path)

def load_tombstones():
  if not os.path.isfile("tombstones.json"):
    return []
  with open("tombstones.json") as file:
    tombstones = json.load(file)
  if not isinstance(tombstones, list) or not all(isinstance(package, str) for package in tombstones):
    raise ValueError("tombstones.json must contain a list of package names")
  return set(tombstones)

def remove_tombstones(tombstones):
  if not tombstones:
    return
  for root, _, files in os.walk(REPO_DIR):
    for name in files:
      if not name.endswith(".apk"):
        continue
      path = os.path.join(root, name)
      package, _, _ = identify_apk(path)
      if package not in tombstones:
        continue
      print("Removing tombstoned application " + package + " from " + path)
      remove_all([
        path,
        path + ".asc",
        path[:-4] + "_src.tar.gz",
      ])
      remove_icons(package)

def identify_apk(path):
  try:
    from fdroidserver import common
    return common.get_apk_id(path)
  except Exception as fdroid_error:
    try:
      result = subprocess.run(
        ["aapt", "dump", "badging", path],
        check=True,
        capture_output=True,
        text=True,
      )
      match = re.search(
        r"^package: name='([^']+)' versionCode='([^']+)' versionName=",
        result.stdout,
        re.MULTILINE,
      )
      if match:
        return match.group(1), int(match.group(2)), None
      error = "aapt output did not contain package and version code"
    except (FileNotFoundError, subprocess.CalledProcessError) as aapt_error:
      error = str(aapt_error)
    print("Warning: could not identify package for " + path + ": " + str(fdroid_error) + "; " + error)
    return None, None, None

def remove_icons(package):
  icon_pattern = re.compile(r"^" + re.escape(package) + r"\.\d+\.png$")
  for directory in os.scandir(REPO_DIR):
    if not directory.is_dir() or not ICON_DIR_PATTERN.fullmatch(directory.name):
      continue
    for icon in os.scandir(directory.path):
      if icon.is_file() and icon_pattern.fullmatch(icon.name):
        remove_all([icon.path])

def prune_stale_icons():
  active_icons = set()
  identification_failed = False
  for entry in os.scandir(REPO_DIR):
    if not entry.is_file() or not entry.name.endswith(".apk"):
      continue
    package, version_code, _ = identify_apk(entry.path)
    if package is None or version_code is None:
      identification_failed = True
      continue
    active_icons.add((package, str(version_code)))
  if identification_failed:
    print("Warning: retaining icons because at least one APK could not be identified")
    return
  for directory in os.scandir(REPO_DIR):
    if not directory.is_dir() or not ICON_DIR_PATTERN.fullmatch(directory.name):
      continue
    for icon in os.scandir(directory.path):
      match = re.fullmatch(r"([A-Za-z0-9._]+)\.(\d+)\.png", icon.name)
      if icon.is_file() and match and (match.group(1), match.group(2)) not in active_icons:
        print("Removing stale icon " + icon.path)
        remove_all([icon.path])

def warn_unknown_files(known_paths):
  known_paths = {os.path.normpath(path) for path in known_paths}
  for root, _, files in os.walk(REPO_DIR):
    for name in files:
      if not name.endswith(".apk"):
        continue
      path = os.path.normpath(os.path.join(root, name))
      if path not in known_paths:
        print("Warning: APK not known to download index: " + path)

if __name__ == "__main__":
  main()
