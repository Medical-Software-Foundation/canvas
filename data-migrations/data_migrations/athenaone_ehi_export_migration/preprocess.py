import argparse
import json

# This script is to preprocess the files received that are not valid json.
# They were given to us as json objects on each invididual line and not
# as valid json arrays.

# Example usage:

# python3 preprocess.py "PHI/allergies_raw.json" "PHI/allergies.json"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="Athena Preprocessor")
    parser.add_argument("input_file")
    parser.add_argument("output_file")

    args = parser.parse_args()
    output_list = []

    with open(args.input_file, "r") as fhandle:
        for row in fhandle:
            output_list.append(json.loads(row))

    output_json = json.dumps(output_list, indent=4)

    with open(args.output_file, "w") as writer:
        writer.write(output_json)
