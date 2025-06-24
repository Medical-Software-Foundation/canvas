import json

mapped_codes = {
    # paste map here;
}


codes_map = {}
name_map = {}


for key, val in mapped_codes.items():
    fdb_code = [v for v in val if v["system"] == "http://www.fdbhealth.com/"][0]
    if key.endswith('|'):
        name_map[key.replace("|", "")] = {"code": fdb_code["code"], "display": fdb_code["display"]}
    else:
        code = key.split("|")[1]
        codes_map[code] = {"code": fdb_code["code"], "display": fdb_code["display"]}

print(json.dumps(name_map))
print(json.dumps(codes_map))


print(len(mapped_codes))
print(len(name_map))
print(len(codes_map))
