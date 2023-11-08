#!/usr/bin/env python3

import json
import os
import re
import requests
import subprocess

def main():
  with open("apks.json") as file:
    apks = json.load(file)
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
      print("Downloading " + apk["name"] + " " + fmt["ver"])
    else:
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
        download(apk["baseUrl"].format_map(fmt), archForceFileName, ignore)
    else:
      download(apk["baseUrl"].format_map(fmt), forceFileName, ignore)

def download(download_url, forceFileName, ignore):
  if forceFileName is not None:
    fullForceFileName = "fdroid/repo/" + forceFileName
    retcode = subprocess.call(["wget", "--progress=dot:mega", "-N", "-O", fullForceFileName, download_url])
  elif download_url.endswith(".apk"):
    retcode = subprocess.call(["wget", "--progress=dot:mega", "-N", "-P", "fdroid/repo", download_url])
  else:
    retcode = subprocess.call(["wget", "--progress=dot:mega", "-nc", "--content-disposition", "-P", "fdroid/repo", download_url])
  if retcode != 0:
    if forceFileName is not None:
      # Under at least some conditions, `wget -O` creates an empty output file
      # on error, which will break subsequent processing. Even if we're not
      # ignoring the error, avoid letting the empty file be added to the cache.
      # (Normally it would be overwritten anyway on the next run, but it might
      # not be if the configuration has changed.)
      try:
        os.unlink(fullForceFileName)
      except FileNotFoundError:
        # Not sure if this can happen, but if it does, it's OK.
        pass
    if not ignore:
      raise Exception("Failed downloading " + download_url)

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
