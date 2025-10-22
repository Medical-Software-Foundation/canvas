# To run the tests, use the command `pytest` in the terminal or uv run pytest.
# Each test is wrapped inside a transaction that is rolled back at the end of the test.
# If you want to modify which files are used for testing, check the [tool.pytest.ini_options] section in pyproject.toml.


from canvas_sdk.test_utils.factories import PatientFactory
from canvas_sdk.v1.data.discount import Discount


# You can use a factory to create a patient instance for testing purposes.
def test_factory() -> None:
    """Test that a patient can be created using the PatientFactory."""
    patient = PatientFactory.create()
    assert patient.id is not None


# if a factory is not available, you can create an instance manually with the data model directly.
def test_model() -> None:
    """Test that a Discount instance can be created."""
    Discount.objects.create(name="10%", adjustment_group="30", adjustment_code="CO", discount=0.10)
    assert Discount.objects.first().pk is not None
