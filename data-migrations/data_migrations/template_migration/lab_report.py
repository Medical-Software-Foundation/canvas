from data_migrations.template_migration.utils import (
    DocumentEncoderMixin,
    MappingMixin,
    FileWriterMixin
)


class LabReportMixin(MappingMixin, FileWriterMixin, DocumentEncoderMixin):
    def load(self, validated_rows):
        ids = set()
        record_count = len(validated_rows)
        record_num = 1
        for payload_dict in validated_rows:
            print(f"Importing {record_num} of {record_count} lab reports.")
            if payload_dict["unique_attribute"] in self.done_records or payload_dict["unique_attribute"] in ids:
                print(' Already did record')
                record_num += 1
                continue
            try:
                canvas_id = self.fumage_helper.perform_create_lab_report(payload_dict["payload"])
                self.done_row(f"{payload_dict['unique_attribute']}|{payload_dict['patient_id']}|{payload_dict['canvas_patient_key']}|{canvas_id}")
                ids.add(payload_dict['unique_attribute'])
            except BaseException as e:
                self.error_row(f"{payload_dict['unique_attribute']}|{payload_dict['patient_id']}|{payload_dict['canvas_patient_key']}", f"{str(e)}")

            record_num += 1