#!/usr/bin/env python3

import json
import os
import re
import requests
from gquery import gquery
from urllib.parse import urlparse
from shutil import rmtree
from packaging.version import Version, InvalidVersion

def main():
  with open("apks.json") as file:
    apks = json.load(file)
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
  os.makedirs("fdroid/repo", exist_ok=True)
  apps_cache = versioncache["apps"]
  for apk in apks:
    fmt={}
    forceFileName = None
    ignore = False
    if "version" in apk:
      verObj = apk["version"]
      if "literal" in verObj:
        fmt["ver"] = verObj["literal"]
      elif "json" in verObj:
        fmt["ver"] = get_version_json(verObj["url"], verObj["json"])
      elif "regex" in verObj:
        fmt["ver"] = get_version_regex(verObj["url"], verObj["regex"])
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
      sfnObj = apk["sourceFileName"]
      if "json" in sfnObj:
        fmt["source_file_name"] = get_version_json(sfnObj["url"], sfnObj["json"])
      elif "regex" in sfnObj:
        fmt["source_file_name"] = get_version_regex(sfnObj["url"], sfnObj["regex"])
    if "forceFileName" in apk:
      forceFileName = apk["forceFileName"]
    if forceFileName is not None:
      fmt["arch"] = "{arch}"
      forceFileName = forceFileName.format_map(fmt)
      fmt["force_file_name"] = forceFileName
      del fmt["arch"]
    if "ignoreErrors" in apk:
      ignore = apk["ignoreErrors"]
    if "architectures" in apk:
      for arch in apk["architectures"]:
        archForceFileName = None if forceFileName is None else forceFileName.format(arch=arch)
        fmt["arch"] = arch
        download(apk["baseUrl"].format_map(fmt), archForceFileName, ignore, app_paths)
    else:
      download(apk["baseUrl"].format_map(fmt), forceFileName, ignore, app_paths)
  print("Writing new version cache")
  with open("versioncache.json", 'w') as file:
    json.dump(versioncache, file)

def add_authentication(url, headers):
  parsed_url = urlparse(url)
  if parsed_url.netloc == "api.github.com":
    token = os.getenv("GITHUB_TOKEN")
    if token:
      headers["Authorization"] = f"Bearer {token}"

def download(download_url, fileName, ignore, paths):
  try:
    headers = {}
    add_authentication(download_url, headers)
    response = requests.get(download_url, headers=headers, allow_redirects=True, stream=True)
    response.raise_for_status()
    if fileName is None:
      fileName = identify_file_name(download_url, response)
    fileName = "fdroid/repo/" + fileName
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

if __name__ == "__main__":
  main()
