import os

SOURCE_DIR = "/Users/Joe/Downloads/immunizations_6_20/"
OUTPUT_FILE = "/Users/joe/Canvas/medical-software-foundation/data-migrations/data_migrations/athena_migration/PHI/immunizations_raw.json"

file_list = [f for f in os.listdir(SOURCE_DIR) if f.startswith("immunization") and f.endswith(".json")]

count = 0
with open(OUTPUT_FILE, "w") as writefile:

    for filename in file_list:
        with open(f"{SOURCE_DIR}{filename}", "r") as fhandle:
            for line in fhandle:
                writefile.write(line)
                count += 1

print(count)