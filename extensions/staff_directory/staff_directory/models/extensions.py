from canvas_sdk.v1.data import ModelExtension, Staff


class CustomStaff(Staff, ModelExtension):
    """Proxy over Staff that scopes reverse relations to this plugin.

    Using this proxy means reverse accessors like `custom_staff.educations.all()`
    do not collide with other plugins that also extend Staff.
    """
