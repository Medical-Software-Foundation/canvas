root_dir = "/Users/reba_magier/Canvas/medical-software-foundation/data-migrations/data_migrations/athenaone_ehi_export_migration/PHI/CLINICALEHIs_1754039588_S-W_3719"

import os
import json
import zipfile
import shutil
from collections import defaultdict

# Path to the root directory containing zipped patient folders
# root_dir = "path/to/patient_zips"
combined_root = os.path.join(root_dir, "combined")
os.makedirs(combined_root, exist_ok=True)

# Step 1: Unzip all .zip files
for item in os.listdir(root_dir):
    if item.endswith(".zip"):
        zip_path = os.path.join(root_dir, item)
        extract_dir = os.path.join(root_dir, os.path.splitext(item)[0])
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        print(f"Extracted {item} to {extract_dir}")

# Step 2: Prepare data holders
folder_data = defaultdict(lambda: defaultdict(list))  # {subfolder: {filename: [json_objects]}}
top_level_data = defaultdict(list)                   # {filename: [json_objects]}

# Step 3: Collect data from all patient folders
for patient_folder in os.listdir(root_dir):
    patient_path = os.path.join(root_dir, patient_folder)
    if os.path.isdir(patient_path) and patient_folder != "combined":
        # Process top-level JSON files
        for filename in os.listdir(patient_path):
            file_path = os.path.join(patient_path, filename)
            if filename.endswith(".json") and os.path.isfile(file_path):
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            top_level_data[filename].extend(data)
                        else:
                            top_level_data[filename].append(data)
                except json.JSONDecodeError as e:
                    print(f"Skipping invalid JSON: {file_path} — {e}")

        # Process subfolders
        for subfolder in os.listdir(patient_path):
            subfolder_path = os.path.join(patient_path, subfolder)
            if os.path.isdir(subfolder_path):
                out_subfolder_path = os.path.join(combined_root, subfolder)
                os.makedirs(out_subfolder_path, exist_ok=True)

                for filename in os.listdir(subfolder_path):
                    file_path = os.path.join(subfolder_path, filename)
                    out_file_path = os.path.join(out_subfolder_path, filename)

                    if filename.endswith(".json"):
                        try:
                            with open(file_path, "r") as f:
                                data = json.load(f)
                                if isinstance(data, list):
                                    folder_data[subfolder][filename].extend(data)
                                else:
                                    folder_data[subfolder][filename].append(data)
                        except json.JSONDecodeError as e:
                            print(f"Skipping invalid JSON: {file_path} — {e}")
                    else:
                        # Copy non-JSON file (avoid name conflicts)
                        if os.path.exists(out_file_path):
                            base, ext = os.path.splitext(filename)
                            counter = 1
                            while os.path.exists(os.path.join(out_subfolder_path, f"{base}_{counter}{ext}")):
                                counter += 1
                            out_file_path = os.path.join(out_subfolder_path, f"{base}_{counter}{ext}")
                        shutil.copy2(file_path, out_file_path)

# Step 4: Write combined subfolder JSON files
for subfolder, files in folder_data.items():
    out_subfolder_path = os.path.join(combined_root, subfolder)
    os.makedirs(out_subfolder_path, exist_ok=True)
    for filename, contents in files.items():
        out_file_path = os.path.join(out_subfolder_path, filename)
        with open(out_file_path, "w") as f:
            json.dump(contents, f, indent=2)

# Step 5: Write top-level combined JSON files
for filename, contents in top_level_data.items():
    out_file_path = os.path.join(combined_root, filename)
    with open(out_file_path, "w") as f:
        json.dump(contents, f, indent=2)

print(f"✅ All data merged into: {combined_root}")
