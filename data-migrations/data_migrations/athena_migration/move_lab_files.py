import os, shutil

SOURCE_DIR = "/Users/Joe/Downloads/labresults_06_28/"
DESTINATION_DIR = "/Users/joe/Canvas/medical-software-foundation/data-migrations/data_migrations/athena_migration/PHI/labresults/labresults_files"

dirs = os.listdir(SOURCE_DIR)

already_transferred = set()
files_already_in_directory = set(os.listdir(DESTINATION_DIR))

for dir in dirs:
    if dir.startswith("labresults_files"):
        print(dir)
        file_list = os.listdir(f"{SOURCE_DIR}{dir}")
        for filename in file_list:
            if filename in files_already_in_directory or filename in already_transferred:
                pass
            else:
                print(f"Moving {filename} to destination directory")
                source_file = f"{SOURCE_DIR}{dir}/{filename}"
                destination_file = f"{DESTINATION_DIR}/{filename}"
                shutil.move(source_file, destination_file)
                already_transferred.add(filename)
