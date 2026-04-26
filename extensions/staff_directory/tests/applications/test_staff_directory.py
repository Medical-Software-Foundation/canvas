from staff_directory.applications.staff_directory import StaffDirectoryApp


class TestOnOpen:
    def test_returns_modal_effect(self):
        app = StaffDirectoryApp()
        effect = app.on_open()

        # Our stub LaunchModalEffect.apply() returns a tuple of key bits.
        assert effect[0] == "LaunchModalEffect"
        assert effect[1] == "/plugin-io/api/staff_directory/app/directory"
        assert effect[2] == "DEFAULT_MODAL"
        assert effect[3] == "Staff Directory"
