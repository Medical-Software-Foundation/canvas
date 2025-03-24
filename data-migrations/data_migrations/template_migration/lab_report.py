from data_migrations.template_migration.utils import (
    MappingMixin,
    FileWriterMixin
)


class LabReportMixin(MappingMixin, FileWriterMixin):
    def load(self, validated_rows):
        for unique_attribute, row in validated_rows:
            if unique_attribute in self.done_records:
                print(' Already did record')
                continue
            try:
                canvas_id = self.fumage_helper.perform_create(row)
                self.done_row(f"{unique_attribute}|{canvas_id}")
            except BaseException as e:
                self.error_row(unique_attribute, str(e))
