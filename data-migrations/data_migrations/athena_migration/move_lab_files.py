import os, shutil

SOURCE_DIR = "/Users/Joe/Downloads/"
DESTINATION_DIR = "/Users/joe/Canvas/medical-software-foundation/data-migrations/data_migrations/athena_migration/PHI/labresults/labresults_files"

dirs = os.listdir(SOURCE_DIR)

for dir in dirs:
    if dir.startswith("labresults_files"):
        file_list = os.listdir(f"{SOURCE_DIR}{dir}")
        for filename in file_list:
            if filename in os.listdir(DESTINATION_DIR):
                print(f"File {filename} already exists in destination directory - skipping")
            else:
                print(f"Moving {filename} to destination directory")
                source_file = f"{SOURCE_DIR}{dir}/{filename}"
                destination_file = f"{DESTINATION_DIR}/{filename}"
                shutil.move(source_file, destination_file)
