# Avon Migration

## Steps

### Setup

1. In the `config.ini` file, create an entry for the instance you will be importing the data into. The following items are required:

* **url** - The full Canvas instance URL that you will be importing data into (i.e. _https://phi-test-customer.canvasmedical.com/_).
* **client_id** - The client ID of the Canvas instance (from `/auth/applications/`).
* **client_secret** - The client secret of the Canvas instance (from `/auth/applications/`).
* **avon_client_id** - The client ID of the Avon EMR API where data is being pulled from.
* **avon_client_secret** - The client secret of the Avon EMR API where data is being pulled from.
* **avon_user_id** - The user ID of the Avon EMR API where data is being pulled from.
* **avon_base_subdomain** - The subdomain of the Avon EMR API that is used in the base URL. For example, `https://customer.avonhealth.com/` would have an `avon_base_subdomain` of `customer`.

### Importing Patients

In Avon migrations, patient records are queried from the API EMR instance. The steps to import patients are as follows:

1. Navigate to the `avon_migration` directory:

```
cd data_migrations/avon_migration
```

2. Scroll down to the bottom of the `create_patients.py` file (underneath `if __name__ == '__main__':`) and change the following:
* Change the `PatientLoader` class `environment` argument to the environment named in your `config.ini` file.
* Comment out everything underneath `loader.make_csv(delimiter=delimiter)` (you only want to run the `loader.make_csv` method in the next step).

3. Run the following command in the terminal. This will fetch the patients from the Avon EMR API and save them locally in a .csv. file:

```
python3 create_patients.py
```

This will create two files in the `PHI/` directory:

* **patients.json** - The response data that is fetched from the API json format.
* **patients.csv** - The patient data transformed into a common Canvas format that is used when creating patients in Canvas.

4. The next step is to validate the patient data. This will check each row to make sure that no required fields are missing or contain data that do not match the format needed to ingest into Canvas. To run validation, comment out the `loader.make_csv` line, and uncomment the following line:

```
valid_rows = loader.validate(delimiter=delimiter)
```

5. Run the following command to run validation on the patients:

```
python3 create_patients.py
```

This will create a report in `results/PHI/errored_patient_validation` with information about the patients that did not pass validation along with the reason.

6. The next step is to ingest the patients that passed validation into the Canvas instance. This is accomplished by the `loader.load` method. It also uses the `valid_rows` created by the validation step, so leave the `loader.validate` method call uncommented and uncomment the `loader.load` method. Again, run the following command:

```
python3 create_patients.py
```

This will create the patients in the Canvas instance through the API. It will also add to the 2 following files:

* **results/PHI/errored_patients.csv** - Shows any errors encountered when attempting to create patients thorugh the Canvas API.
* **PHI/patient_id_map.json** - Keeps track of the Avon/Canvas patient ID mappings. These are used as references in subsequent imports (i.e. conditions, etc.).

### Importing Appointments

Historical appointments are ingested from the Avon API into the Canvas instance. The steps to import appointments are as follows:

1. In the `create_appointments.py` file, add the Canvas practice location ID for the location that appointments will fall under to the value of `self.default_location`.

2. Make sure the `mappings/doctor_map.json` file is updated with the mappings between the Avon staff member IDs to the staff member IDs in Canvas. This file is currently manually managed from data in the Google drive.

3. In the Canvas instance, make sure there is a Note Type (under Settings > Event and Note Types) with the following information:
* **Name** Avon Historical Note
* **Icon** history
* **System** INTERNAL
* **Code** avon_historical_note
* **Display** Avon Historical Note
* **Is Schedulable** True (checked)
* **Is Billable** False (unchecked)
* **Is Active** True (checked)

4. At the bottom of the file, change the `environment` argument to the `AppointmentLoader` initialization to the value of the environment you are using (as defined in `config.ini`).

5. Uncomment the `loader.make_csv` method call and comment everything below it. Run the file with the following command:

```
python3 create_appointments.py
```

This command will create the following files:

* **appointments.json** - The response data pulled from the Avon API.
* **appointments.csv** - The response data pulled from the Avon API transformed into a format used to ingest into Canvas.

And add to the following files:

* **results/ignored_appointments.csv** - Appointments that have been cancelled or have more than one attendee listed are ignored (and not added to `appointments.csv`). These records are kept track of in this file.

6. The next step is to validate the appointment data. To do this, comment out the `loader.make_csv` method call and uncomment the `loader.validate` method call. Then run the following command:

```
python3 create_appointments.py
```

If there are any appointments that do not pass validation, they will be added to the `results/PHI/errored_appointment_validation.json` file.

7. The next step is to import the appointment data into the Canvas instance. To do this, uncomment the `loader.load` method call. Also, add a date to the `end_date_time_frame` argument. This will skip loading appointments with a start time greater than the date passed. Then run the following command:

```
python3 create_appointments.py
```

This will create the Appointments in the Canvas instance. The following files will show the results of the import:

* **results/done_appointments.csv** - Shows the successfully loaded appointments.
* **results/ignored_appointments.csv** - Shows the ignored appointments. This could be due to the start date being greater than `end_date_time_frame` or the patient not being found in the patient map file.
* **results/errored_appointments.csv** - The appointments that resulted in errors when the creation payload was sent to the API. Includes the error from the Canvas API.
* **results/errored_note_state_events.csv** - Show any errors that resulted from trying to lock historical notes.
