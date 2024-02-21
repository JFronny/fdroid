# we have jq at home

import re

def gquery(json, query):
  if not isinstance(query, list):
    if isinstance(query, str) or isinstance(query, int):
      return json[query]
    else:
      raise Exception("Unsupported query type")
  if not query:
    return json
  mode = "normal"
  for query_part in query:
    if mode == "normal":
      if isinstance(query_part, str):
        if query_part.startswith("@gq:"):
          if query_part == "@gq:whereeq":
            if not isinstance(json, list):
              raise Exception("Cannot perform whereeq on non-list")
            mode = "whereeq"
          elif query_part == "@gq:whereregex":
            if not isinstance(json, list):
              raise Exception("Cannot perform whereregex on non-list")
            mode = "whereregex"
          elif query_part == "@gq:regex":
            if not isinstance(json, str):
              raise Exception("Cannot perform regex on non-string")
            mode = "regex"
          else:
            raise Exception("Unsupported gq: " + query_part)
        else:
          json = json[query_part]
      elif isinstance(query_part, int):
        json = json[query_part]
      else:
        raise Exception("Unsupported query type")
    elif mode == "whereeq":
      if not isinstance(query_part, list) or len(query_part) != 2:
        raise Exception("Unsupported whereeq query")
      found = []
      for json_part in json:
        if gquery(json_part, query_part[0]) == query_part[1]:
          found.append(json_part)
      if not found:
        raise Exception("No matching element")
      else:
        json = found
        mode = "normal"
    elif mode == "whereregex":
      if not isinstance(query_part, list) or len(query_part) != 2 or not isinstance(query_part[1], str):
        raise Exception("Unsupported whereregex query")
      found = []
      for json_part in json:
        subpart = gquery(json_part, query_part[0])
        if not isinstance(subpart, str):
          continue
        match = re.match(query_part[1], subpart)
        if match:
          found.append(json_part)
      if not found:
        raise Exception("No matching element")
      else:
        json = found
        mode = "normal"
    elif mode == "regex":
      if not isinstance(query_part, str):
        raise Exception("Unsupported regex query")
      match = re.match(query_part, json)
      if not match:
        raise Exception("No match found")
      json = match.group(1)
      mode = "normal"
    else:
      raise Exception("Unsupported mode")
  if mode != "normal":
    raise Exception("Unexpected final mode")
  return json
