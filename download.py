#!/usr/bin/env python3

import json
import os
import re
import requests
import subprocess
from urllib.parse import urlparse
from shutil import rmtree

def main():
  with open("apks.json") as file:
    apks = json.load(file)
  if os.path.isfile("versioncache.json"):
    with open("versioncache.json") as file:
      versioncache = json.load(file)
    if "format" not in versioncache or versioncache["format"] != 2:
      print("Found outdated version cache, creating new")
      versioncache = {"format": 2, "apps": {}}
      rmtree("fdroid/repo")
    else:
      print("Found version cache, using")
  else:
    print("Version cache not found, creating")
    versioncache = {"format": 2, "apps": {}}
  os.makedirs("fdroid/repo", exist_ok=True)
  apps_cache = versioncache["apps"]
  for apk in apks:
    fmt={}
    forceFileName = None
    ignore = False
    if "version" in apk:
      verObj = apk["version"]
      if "json" in verObj:
        fmt["ver"] = get_version_json(verObj["url"], verObj["json"])
      elif "regex" in verObj:
        fmt["ver"] = get_version_regex(verObj["url"], verObj["regex"])
      fmt["ver_stripped"] = fmt["ver"].lstrip("v")
      fmt["ver_splitted"] = fmt["ver"].split(".")
      if apk["name"] in apps_cache:
        if apps_cache[apk["name"]]["version"] == fmt["ver"]:
          print("Skipping " + apk["name"] + ": already up to date")
          for path in apps_cache[apk["name"]]["paths"]:
            if not os.path.isfile(path):
              print("Warning: missing file for application: " + path)
          continue
        else:
          print("Updating " + apk["name"] + ": new version is available")
          for path in apps_cache[apk["name"]]["paths"]:
            if os.path.isfile(path):
              os.remove(path)
          apps_cache[apk["name"]] = {"version": fmt["ver"], "paths": []}
      else:
        print("Adding " + apk["name"] + ": new application")
        apps_cache[apk["name"]] = {"version": fmt["ver"], "paths": []}
      app_paths = apps_cache[apk["name"]]["paths"]
      print("Downloading " + apk["name"] + " " + fmt["ver"])
    else:
      app_paths = []
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

def download(download_url, fileName, ignore, paths):
  try:
    response = requests.get(download_url, allow_redirects=True, stream=True)
    chunk_size = 8192
    if fileName is None:
      if download_url.endswith(".apk"):
        fileName = os.path.basename(urlparse(download_url).path)
      elif "Content-Disposition" in response.headers:
        match = re.search('filename="(.+)"', response.headers["Content-Disposition"])
        if match:
          fileName = match.group(1)
        else:
          raise Exception("Could not get filename from content disposition of " + download_url)
      else:
        raise Exception("Could not get filename from " + download_url)
    fileName = "fdroid/repo/" + fileName
    print("Using target file " + fileName)
    with open(fileName, 'wb') as file:
      for chunk in response.iter_content(chunk_size):
        file.write(chunk)
    paths += [fileName]
  except Exception as e:
    if fileName is not None:
      # ensure we don't get empty leftover files
      try:
        os.unlink(fullForceFileName)
      except FileNotFoundError:
        # Not sure if this can happen, but if it does, it's OK.
        pass
    if not ignore:
      raise Exception("Failed downloading " + download_url)
    else:
      print("Ignoring error:")
      print(e)

def get_version_regex(url, query):
  request = requests.get(url)
  regex = re.search(query, request.text)
  return regex.group(1)

def get_version_json(url, query):
  request = requests.get(url)
  version = request.json()
  if not isinstance(query, list):
    return version[query]
  for query_part in query:
    version = version[query_part]
  return version

if __name__ == "__main__":
  main()
