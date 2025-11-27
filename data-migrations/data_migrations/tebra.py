#!/usr/bin/env python
"""
Fetch patients from Tebra (formerly Kareo) via SOAP API.

Usage:
    python tebra_patient_fetch.py

Requirements:
    pip install zeep
"""

import os
from time import sleep

from lxml import etree
from zeep import Client
from zeep.exceptions import Fault, XMLParseError
from zeep.helpers import serialize_object
from zeep.plugins import HistoryPlugin

from data_migrations.utils import fetch_from_json, write_to_json


RETRYABLE_RATE_LIMIT_SUBSTRING = "endpoint requested more than allowed"
MAX_RETRIES = 5
BACKOFF_SECONDS = 1.5

WSDL_URL = "https://webservice.kareo.com/services/soap/2.1/KareoServices.svc?wsdl"

DEFAULT_PRACTICE_NAME_FILTERS = [
    {"PracticeName": "Geiss MED Nevada, PC"},
    {"PracticeName": "Senior Doc Arizona, PC"},
    {"PracticeName": "Senior Doc Idaho, PC"},
    {"PracticeName": "Senior Doc Oregon PC"},
    {"PracticeName": "Senior Doc Washington"},
    {"PracticeName": "SeniorDoc CA"},
    {"PracticeName": "SeniorDoc Tennessee PC"},
    {"PracticeName": "SeniorDoc TN"},
    {"PracticeName": "SeniorDoc TX"},
]

PRACTICE_FIELDS_TO_RETURN = {
    "Active": True,
    "AdministratorAddressLine1": True,
    "AdministratorAddressLine2": True,
    "AdministratorCity": True,
    "AdministratorCountry": True,
    "AdministratorEmail": True,
    "AdministratorFax": True,
    "AdministratorFaxExt": True,
    "AdministratorFullName": True,
    "AdministratorPhone": True,
    "AdministratorPhoneExt": True,
    "AdministratorState": True,
    "AdministratorZipCode": True,
    "BillingContactAddressLine1": True,
    "BillingContactAddressLine2": True,
    "BillingContactCity": True,
    "BillingContactCountry": True,
    "BillingContactEmail": True,
    "BillingContactFax": True,
    "BillingContactFaxExt": True,
    "BillingContactFullName": True,
    "BillingContactPhone": True,
    "BillingContactPhoneExt": True,
    "BillingContactState": True,
    "BillingContactZipCode": True,
    "CreatedDate": True,
    "Email": True,
    "Fax": True,
    "FaxExt": True,
    "ID": True,
    "LastModifiedDate": True,
    "NPI": True,
    "Notes": True,
    "Phone": True,
    "PhoneExt": True,
    "PracticeAddressLine1": True,
    "PracticeAddressLine2": True,
    "PracticeCity": True,
    "PracticeCountry": True,
    "PracticeName": True,
    "PracticeState": True,
    "PracticeZipCode": True,
    "SubscriptionEdition": True,
    "TaxID": True,
    "WebSite": True,
    "kFaxNumber": True,
}

PATIENT_FIELDS_TO_RETURN = {
    "Active": True,
    "AddressLine1": True,
    "AddressLine2": True,
    "Adjustments": True,
    "Age": True,
    "AlertMessage": True,
    "AlertShowWhenDisplayingPatientDetails": True,
    "AlertShowWhenEnteringEncounters": True,
    "AlertShowWhenPostingPayments": True,
    "AlertShowWhenPreparingPatientStatements": True,
    "AlertShowWhenSchedulingAppointments": True,
    "AlertShowWhenViewingClaimDetails": True,
    "Charges": True,
    "City": True,
    "CollectionCategoryName": True,
    "Country": True,
    "CreatedDate": True,
    "DOB": True,
    "DefaultCaseConditionRelatedToAbuse": True,
    "DefaultCaseConditionRelatedToAutoAccident": True,
    "DefaultCaseConditionRelatedToAutoAccidentState": True,
    "DefaultCaseConditionRelatedToEPSDT": True,
    "DefaultCaseConditionRelatedToEmergency": True,
    "DefaultCaseConditionRelatedToEmployment": True,
    "DefaultCaseConditionRelatedToFamilyPlanning": True,
    "DefaultCaseConditionRelatedToOther": True,
    "DefaultCaseConditionRelatedToPregnancy": True,
    "DefaultCaseDatesAccidentDate": True,
    "DefaultCaseDatesAcuteManifestationDate": True,
    "DefaultCaseDatesInjuryEndDate": True,
    "DefaultCaseDatesInjuryStartDate": True,
    "DefaultCaseDatesLastMenstrualPeriodDate": True,
    "DefaultCaseDatesLastSeenDate": True,
    "DefaultCaseDatesLastXRayDate": True,
    "DefaultCaseDatesReferralDate": True,
    "DefaultCaseDatesRelatedDisabilityEndDate": True,
    "DefaultCaseDatesRelatedDisabilityStartDate": True,
    "DefaultCaseDatesRelatedHospitalizationEndDate": True,
    "DefaultCaseDatesRelatedHospitalizationStartDate": True,
    "DefaultCaseDatesSameOrSimilarIllnessEndDate": True,
    "DefaultCaseDatesSameOrSimilarIllnessStartDate": True,
    "DefaultCaseDatesUnableToWorkEndDate": True,
    "DefaultCaseDatesUnableToWorkStartDate": True,
    "DefaultCaseDescription": True,
    "DefaultCaseID": True,
    "DefaultCaseName": True,
    "DefaultCasePayerScenario": True,
    "DefaultCaseReferringProviderFullName": True,
    "DefaultCaseReferringProviderID": True,
    "DefaultCaseSendPatientStatements": True,
    "DefaultRenderingProviderFullName": True,
    "DefaultRenderingProviderId": True,
    "DefaultServiceLocationBillingName": True,
    "DefaultServiceLocationFaxPhone": True,
    "DefaultServiceLocationFaxPhoneExt": True,
    "DefaultServiceLocationId": True,
    "DefaultServiceLocationName": True,
    "DefaultServiceLocationNameAddressLine1": True,
    "DefaultServiceLocationNameAddressLine2": True,
    "DefaultServiceLocationNameCity": True,
    "DefaultServiceLocationNameCountry": True,
    "DefaultServiceLocationNameState": True,
    "DefaultServiceLocationNameZipCode": True,
    "DefaultServiceLocationPhone": True,
    "DefaultServiceLocationPhoneExt": True,
    "EmailAddress": True,
    "EmergencyName": True,
    "EmergencyPhone": True,
    "EmergencyPhoneExt": True,
    "EmployerName": True,
    "EmploymentStatus": True,
    "FirstName": True,
    "Gender": True,
    "GuarantorDifferentThanPatient": True,
    "GuarantorFirstName": True,
    "GuarantorLastName": True,
    "GuarantorMiddleName": True,
    "GuarantorPrefix": True,
    "GuarantorSuffix": True,
    "HomePhone": True,
    "HomePhoneExt": True,
    "ID": True,
    "InsuranceBalance": True,
    "InsurancePayments": True,
    "LastAppointmentDate": True,
    "LastDiagnosis": True,
    "LastEncounterDate": True,
    "LastModifiedDate": True,
    "LastName": True,
    "LastPaymentDate": True,
    "LastStatementDate": True,
    "MaritalStatus": True,
    "MedicalRecordNumber": True,
    "MiddleName": True,
    "MobilePhone": True,
    "MobilePhoneExt": True,
    "MostRecentNote1Date": True,
    "MostRecentNote1Message": True,
    "MostRecentNote1User": True,
    "MostRecentNote2Date": True,
    "MostRecentNote2Message": True,
    "MostRecentNote2User": True,
    "MostRecentNote3Date": True,
    "MostRecentNote3Message": True,
    "MostRecentNote3User": True,
    "MostRecentNote4Date": True,
    "MostRecentNote4Message": True,
    "MostRecentNote4User": True,
    "PatientBalance": True,
    "PatientFullName": True,
    "PatientPayments": True,
    "PracticeId": True,
    "PracticeName": True,
    "Prefix": True,
    "PrimaryCarePhysicianFullName": True,
    "PrimaryCarePhysicianId": True,
    "PrimaryInsurancePolicyCompanyID": True,
    "PrimaryInsurancePolicyCompanyName": True,
    "PrimaryInsurancePolicyCopay": True,
    "PrimaryInsurancePolicyDeductible": True,
    "PrimaryInsurancePolicyEffectiveEndDate": True,
    "PrimaryInsurancePolicyEffectiveStartDate": True,
    "PrimaryInsurancePolicyGroupNumber": True,
    "PrimaryInsurancePolicyInsuredAddressLine1": True,
    "PrimaryInsurancePolicyInsuredAddressLine2": True,
    "PrimaryInsurancePolicyInsuredCity": True,
    "PrimaryInsurancePolicyInsuredCountry": True,
    "PrimaryInsurancePolicyInsuredDateOfBirth": True,
    "PrimaryInsurancePolicyInsuredFullName": True,
    "PrimaryInsurancePolicyInsuredGender": True,
    "PrimaryInsurancePolicyInsuredIDNumber": True,
    "PrimaryInsurancePolicyInsuredNotes": True,
    "PrimaryInsurancePolicyInsuredSocialSecurityNumber": True,
    "PrimaryInsurancePolicyInsuredState": True,
    "PrimaryInsurancePolicyInsuredZipCode": True,
    "PrimaryInsurancePolicyNumber": True,
    "PrimaryInsurancePolicyPatientRelationshipToInsured": True,
    "PrimaryInsurancePolicyPlanAddressLine1": True,
    "PrimaryInsurancePolicyPlanAddressLine2": True,
    "PrimaryInsurancePolicyPlanAdjusterFullName": True,
    "PrimaryInsurancePolicyPlanCity": True,
    "PrimaryInsurancePolicyPlanCountry": True,
    "PrimaryInsurancePolicyPlanFaxNumber": True,
    "PrimaryInsurancePolicyPlanFaxNumberExt": True,
    "PrimaryInsurancePolicyPlanID": True,
    "PrimaryInsurancePolicyPlanName": True,
    "PrimaryInsurancePolicyPlanPhoneNumber": True,
    "PrimaryInsurancePolicyPlanPhoneNumberExt": True,
    "PrimaryInsurancePolicyPlanState": True,
    "PrimaryInsurancePolicyPlanZipCode": True,
    "ReferralSource": True,
    "ReferringProviderFullName": True,
    "ReferringProviderId": True,
    "SSN": True,
    "SecondaryInsurancePolicyCompanyID": True,
    "SecondaryInsurancePolicyCompanyName": True,
    "SecondaryInsurancePolicyCopay": True,
    "SecondaryInsurancePolicyDeductible": True,
    "SecondaryInsurancePolicyEffectiveEndDate": True,
    "SecondaryInsurancePolicyEffectiveStartDate": True,
    "SecondaryInsurancePolicyGroupNumber": True,
    "SecondaryInsurancePolicyInsuredAddressLine1": True,
    "SecondaryInsurancePolicyInsuredAddressLine2": True,
    "SecondaryInsurancePolicyInsuredCity": True,
    "SecondaryInsurancePolicyInsuredCountry": True,
    "SecondaryInsurancePolicyInsuredDateOfBirth": True,
    "SecondaryInsurancePolicyInsuredFullName": True,
    "SecondaryInsurancePolicyInsuredGender": True,
    "SecondaryInsurancePolicyInsuredIDNumber": True,
    "SecondaryInsurancePolicyInsuredNotes": True,
    "SecondaryInsurancePolicyInsuredSocialSecurityNumber": True,
    "SecondaryInsurancePolicyInsuredState": True,
    "SecondaryInsurancePolicyInsuredZipCode": True,
    "SecondaryInsurancePolicyNumber": True,
    "SecondaryInsurancePolicyPatientRelationshipToInsured": True,
    "SecondaryInsurancePolicyPlanAddressLine1": True,
    "SecondaryInsurancePolicyPlanAddressLine2": True,
    "SecondaryInsurancePolicyPlanAdjusterFullName": True,
    "SecondaryInsurancePolicyPlanCity": True,
    "SecondaryInsurancePolicyPlanCountry": True,
    "SecondaryInsurancePolicyPlanFaxNumber": True,
    "SecondaryInsurancePolicyPlanFaxNumberExt": True,
    "SecondaryInsurancePolicyPlanID": True,
    "SecondaryInsurancePolicyPlanName": True,
    "SecondaryInsurancePolicyPlanPhoneNumber": True,
    "SecondaryInsurancePolicyPlanPhoneNumberExt": True,
    "SecondaryInsurancePolicyPlanState": True,
    "SecondaryInsurancePolicyPlanZipCode": True,
    "State": True,
    "StatementNote": True,
    "Suffix": True,
    "TotalBalance": True,
    "WorkPhone": True,
    "WorkPhoneExt": True,
    "ZipCode": True,
}

APPOINTMENT_FIELDS_TO_RETURN = {
    "ID": True,
    "CreatedDate": True,
    "LastModifiedDate": True,
    "PracticeName": True,
    "PracticeID": True,
    "Type": True,
    "ConfirmationStatus": True,
    "ServiceLocationName": True,
    "ServiceLocationID": True,
    "PatientID": True,
    "PatientFullName": True,
    "PatientCaseID": True,
    "PatientCaseName": True,
    "PatientCasePayerScenario": True,
    "AuthorizationID": True,
    "AuthorizationNumber": True,
    "AuthorizationStartDate": True,
    "AuthorizationEndDate": True,
    "AuthorizationInsurancePlan": True,
    "StartDate": True,
    "EndDate": True,
    "AllDay": True,
    "Recurring": True,
    "Notes": True,
    "AppointmentDuration": True,
    "AppointmentReason1": True,
    "AppointmentReason2": True,
    "AppointmentReason3": True,
    "AppointmentReason4": True,
    "AppointmentReason5": True,
    "AppointmentReason6": True,
    "AppointmentReason7": True,
    "AppointmentReason8": True,
    "AppointmentReason9": True,
    "AppointmentReason10": True,
    "AppointmentReasonID1": True,
    "AppointmentReasonID2": True,
    "AppointmentReasonID3": True,
    "AppointmentReasonID4": True,
    "AppointmentReasonID5": True,
    "AppointmentReasonID6": True,
    "AppointmentReasonID7": True,
    "AppointmentReasonID8": True,
    "AppointmentReasonID9": True,
    "AppointmentReasonID10": True,
    "ResourceName1": True,
    "ResourceName2": True,
    "ResourceName3": True,
    "ResourceName4": True,
    "ResourceName5": True,
    "ResourceName6": True,
    "ResourceName7": True,
    "ResourceName8": True,
    "ResourceName9": True,
    "ResourceName10": True,
    "ResourceID1": True,
    "ResourceID2": True,
    "ResourceID3": True,
    "ResourceID4": True,
    "ResourceID5": True,
    "ResourceID6": True,
    "ResourceID7": True,
    "ResourceID8": True,
    "ResourceID9": True,
    "ResourceID10": True,
    "ResourceTypeID1": True,
    "ResourceTypeID2": True,
    "ResourceTypeID3": True,
    "ResourceTypeID4": True,
    "ResourceTypeID5": True,
    "ResourceTypeID6": True,
    "ResourceTypeID7": True,
    "ResourceTypeID8": True,
    "ResourceTypeID9": True,
    "ResourceTypeID10": True,
}

CHARGE_FIELDS_TO_RETURN = {
    "ID": True,
    "CreatedDate": True,
    "LastModifiedDate": True,
    "PracticeName": True,
    "EncounterID": True,
    "PatientID": True,
    "PatientName": True,
    "PatientDateOfBirth": True,
    "CaseName": True,
    "CasePayerScenario": True,
    "ServiceStartDate": True,
    "ServiceEndDate": True,
    "PostingDate": True,
    "BatchNumber": True,
    "SchedulingProviderName": True,
    "RenderingProviderName": True,
    "SupervisingProviderName": True,
    "ReferringProviderName": True,
    "ServiceLocationName": True,
    "ProcedureCode": True,
    "ProcedureName": True,
    "ProcedureCodeCategory": True,
    "ProcedureModifier1": True,
    "ProcedureModifier2": True,
    "ProcedureModifier3": True,
    "ProcedureModifier4": True,
    "EncounterDiagnosisID1": True,
    "EncounterDiagnosisID2": True,
    "EncounterDiagnosisID3": True,
    "EncounterDiagnosisID4": True,
    "Units": True,
    "UnitCharge": True,
    "TotalCharges": True,
    "AdjustedCharges": True,
    "Receipts": True,
    "PatientBalance": True,
    "InsuranceBalance": True,
    "TotalBalance": True,
    "BilledTo": True,
    "Status": True,
    "PracticeID": True,
    "AppointmentID": True,
    "SchedulingProviderID": True,
    "RenderingProviderID": True,
    "SupervisingProviderID": True,
    "ReferringProviderID": True,
    "CopayAmount": True,
    "CopayMethod": True,
    "CopayCategory": True,
    "CopayReference": True,
    "Minutes": True,
    "LineNote": True,
    "RefCode": True,
    "TypeOfService": True,
    "HospitalizationStartDate": True,
    "HospitalizationEndDate": True,
    "LocalUseBox10d": True,
    "LocalUseBox19": True,
    "DoNotSendClaimElectronically": True,
    "DoNotSendElectronicallyToSecondary": True,
    "EClaimNoteType": True,
    "EClaimNote": True,
    "ServiceLocationId": True,
    "ServiceLocationFacilityID": True,
    "AllowedAmount": True,
    "ExpectedAmount": True,
    "PrimaryInsuranceAddressLine1": True,
    "PrimaryInsuranceAddressLine2": True,
    "PrimaryInsuranceCity": True,
    "PrimaryInsuranceState": True,
    "PrimaryInsuranceCountry": True,
    "PrimaryInsuranceZipCode": True,
    "PrimaryInsuranceBatchID": True,
    "PrimaryInsuranceFirstBillDate": True,
    "PrimaryInsuranceLastBillDate": True,
    "PrimaryInsurancePaymentID": True,
    "PrimaryInsurancePaymentPostingDate": True,
    "PrimaryInsuranceAdjudicationDate": True,
    "PrimaryInsurancePaymentRef": True,
    "PrimaryInsurancePaymentMethodDesc": True,
    "PrimaryInsurancePaymentCategoryDesc": True,
    "PrimaryInsuranceInsuranceAllowed": True,
    "PrimaryInsuranceInsuranceContractAdjustment": True,
    "PrimaryInsuranceInsuranceContractAdjustmentReason": True,
    "PrimaryInsuranceInsuranceSecondaryAdjustment": True,
    "PrimaryInsuranceInsuranceSecondaryAdjustmentReason": True,
    "PrimaryInsuranceInsurancePayment": True,
    "PrimaryInsuranceInsuranceDeductible": True,
    "PrimaryInsuranceInsuranceCoinsurance": True,
    "PrimaryInsuranceInsuranceCopay": True,
    "PrimaryInsuranceCompanyName": True,
    "PrimaryInsurancePlanName": True,
    "SecondaryInsuranceAddressLine1": True,
    "SecondaryInsuranceAddressLine2": True,
    "SecondaryInsuranceCity": True,
    "SecondaryInsuranceState": True,
    "SecondaryInsuranceCountry": True,
    "SecondaryInsuranceZipCode": True,
    "SecondaryInsuranceBatchID": True,
    "SecondaryInsuranceFirstBillDate": True,
    "SecondaryInsuranceLastBillDate": True,
    "SecondaryInsurancePaymentID": True,
    "SecondaryInsurancePaymentPostingDate": True,
    "SecondaryInsuranceAdjudicationDate": True,
    "SecondaryInsurancePaymentRef": True,
    "SecondaryInsurancePaymentMethodDesc": True,
    "SecondaryInsurancePaymentCategoryDesc": True,
    "SecondaryInsuranceInsuranceAllowed": True,
    "SecondaryInsuranceInsuranceContractAdjustment": True,
    "SecondaryInsuranceInsuranceContractAdjustmentReason": True,
    "SecondaryInsuranceInsuranceSecondaryAdjustment": True,
    "SecondaryInsuranceInsuranceSecondaryAdjustmentReason": True,
    "SecondaryInsuranceInsurancePayment": True,
    "SecondaryInsuranceInsuranceDeductible": True,
    "SecondaryInsuranceInsuranceCoinsurance": True,
    "SecondaryInsuranceInsuranceCopay": True,
    "SecondaryInsuranceCompanyName": True,
    "SecondaryInsurancePlanName": True,
    "TertiaryInsuranceAddressLine1": True,
    "TertiaryInsuranceAddressLine2": True,
    "TertiaryInsuranceCity": True,
    "TertiaryInsuranceState": True,
    "TertiaryInsuranceCountry": True,
    "TertiaryInsuranceZipCode": True,
    "TertiaryInsuranceBatchID": True,
    "TertiaryInsurancePaymentID": True,
    "TertiaryInsurancePaymentPostingDate": True,
    "TertiaryInsuranceAdjudicationDate": True,
    "TertiaryInsurancePaymentRef": True,
    "TertiaryInsurancePaymentMethodDesc": True,
    "TertiaryInsurancePaymentCategoryDesc": True,
    "TertiaryInsuranceInsuranceAllowed": True,
    "TertiaryInsuranceInsuranceContractAdjustment": True,
    "TertiaryInsuranceInsuranceContractAdjustmentReason": True,
    "TertiaryInsuranceInsuranceSecondaryAdjustment": True,
    "TertiaryInsuranceInsuranceSecondaryAdjustmentReason": True,
    "TertiaryInsuranceInsurancePayment": True,
    "TertiaryInsuranceInsuranceDeductible": True,
    "TertiaryInsuranceInsuranceCoinsurance": True,
    "TertiaryInsuranceInsuranceCopay": True,
    "TertiaryInsuranceCompanyName": True,
    "TertiaryInsuranceCompanyPlanName": True,
    "PatientBatchID": True,
    "PatientFirstBillDate": True,
    "PatientLastBillDate": True,
    "PatientPaymentRef": True,
    "PatientPaymentID": True,
    "PatientPaymentPostingDate": True,
    "PatientPaymentMethodDesc": True,
    "PatientPaymentCategoryDesc": True,
    "PatientPaymentAmount": True,
    "OtherAdjustment": True,
}

ENCOUNTER_FIELDS_TO_RETURN = {
    "AppointmentID": True,
    "BatchNumber": True,
    "CaseID": True,
    "CaseName": True,
    "CasePayerScenario": True,
    "CreatedDate": True,
    "EncounterID": True,
    "EncounterStatus": True,
    "HospitalizationEndDate": True,
    "HospitalizationStartDate": True,
    "LastModifiedDate": True,
    "PatientFirstName": True,
    "PatientID": True,
    "PatientLastName": True,
    "PatientMiddleName": True,
    "PatientPrefix": True,
    "PatientSufix": True,
    "Payment": True,
    "PlaceOfServiceCode": True,
    "PlaceOfServiceName": True,
    "PostDate": True,
    "PracticeID": True,
    "PracticeName": True,
    "ReferringProvider": True,
    "RenderingProvider": True,
    "SchedulingProvider": True,
    "ServiceEndDate": True,
    "ServiceLocationID": True,
    "ServiceLocationName": True,
    "ServiceStartDate": True,
    "SupervisingProvider": True
}


def _format_envelope(envelope: etree._Element | None) -> str:
    if envelope is None:
        return "<no envelope>"
    return etree.tostring(envelope, pretty_print=True, encoding="unicode")


def _extract_error_message(envelope: etree._Element | None) -> str | None:
    if envelope is None:
        return None
    matches = envelope.xpath('.//*[local-name()="ErrorMessage"]/text()')
    return matches[0] if matches else None


class TebraSoapClient:
    """Reusable SOAP client for interacting with the Tebra API."""

    def __init__(
        self,
        username: str,
        password: str,
        customer_key: str,
        *,
        wsdl: str = WSDL_URL,
        max_retries: int = MAX_RETRIES,
        backoff_seconds: float = BACKOFF_SECONDS,
        log_envelopes: bool | None = None,
    ) -> None:
        self.username = username
        self.password = password
        self.customer_key = customer_key
        self.wsdl = wsdl
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        env_debug = os.getenv("TEBRA_SOAP_DEBUG_ENVELOPES")
        self.log_envelopes = (
            log_envelopes
            if log_envelopes is not None
            else env_debug is not None and env_debug.lower() in {"1", "true", "yes"}
        )
        self.history = HistoryPlugin()
        self.client = Client(wsdl, plugins=[self.history])

    def call(
        self,
        operation: str,
        *,
        fields: dict[str, bool] | None = None,
        filter: dict | None = None,
        extra_request: dict | None = None,
        max_retries: int | None = None,
    ):
        request = {
            "RequestHeader": {
                "User": self.username,
                "Password": self.password,
                "CustomerKey": self.customer_key,
            }
        }

        if filter:
            request["Filter"] = filter
        if fields:
            request["Fields"] = fields
        if extra_request:
            request.update(extra_request)

        attempt = 0
        max_attempts = max_retries or self.max_retries

        while True:
            attempt += 1
            try:
                operation_fn = getattr(self.client.service, operation)
                return operation_fn(request=request)
            except XMLParseError as exc:
                error_message = _extract_error_message(
                    self.history.last_received.get("envelope")
                    if self.history.last_received
                    else None
                )
                self._log_fault(exc, error_message)

                if (
                    error_message
                    and RETRYABLE_RATE_LIMIT_SUBSTRING in error_message
                    and attempt < max_attempts
                ):
                    backoff = self.backoff_seconds * attempt
                    print(
                        f"Rate limit encountered for {operation} (attempt {attempt}/{max_attempts}). "
                        f"Sleeping {backoff:.1f}s before retrying."
                    )
                    sleep(backoff)
                    print(f"Retrying {operation} (attempt {attempt}/{max_attempts})...")
                    continue

                raise

    def _log_fault(self, exc: XMLParseError, error_message: str | None = None) -> None:
        print(f"XMLParseError while calling Tebra SOAP operation: {exc}")
        if error_message:
            print(f"SOAP error message: {error_message}")
        if self.log_envelopes:
            if self.history.last_sent:
                print(
                    "Request envelope:\n",
                    _format_envelope(self.history.last_sent.get("envelope")),
                )
            if self.history.last_received:
                print(
                    "Response envelope:\n",
                    _format_envelope(self.history.last_received.get("envelope")),
                )


    def get_tebra_data(
        self,
        *,
        filters: list[dict] | None = None,
        fields: dict[str, bool] | None = None,
        operation: str,
        special_data_name: str | None = None
    ) -> list[dict]:
        """
        Fetch data from Tebra SOAP API.
        """
        output_file = f"PHI/{operation.lower()}s.json"
        if os.path.exists(output_file):
            print(f"Grabbing data from {output_file}")
            return fetch_from_json(output_file)
        
        try:
            data: list[dict] = []
            iterable_filters = filters or [{}]
            for request_payload in iterable_filters:
                if isinstance(request_payload, dict) and any(
                    key in request_payload for key in ("filter", "fields", "extra_request")
                ):
                    filter_payload = request_payload.get("filter")
                    fields_payload = request_payload.get("fields", fields)
                    extra_request = request_payload.get("extra_request")
                else:
                    filter_payload = request_payload
                    fields_payload = fields
                    extra_request = None

                response = self.call(
                    f"Get{operation}s",
                    filter=filter_payload,
                    fields=fields_payload,
                    extra_request=extra_request,
                )
                data_container = getattr(response, f"{operation}s", None)
                if data_container is None and special_data_name:
                    data_data = getattr(response, special_data_name, None)
                else:
                    data_data = getattr(data_container, special_data_name or f"{operation}Data", None)
                if data_data:
                    data.extend([serialize_object(item, dict) for item in data_data])
            write_to_json(output_file, data)
            print(f"Wrote {len(data)} data to {output_file}")
            return data
        except Fault as fault:
            print(f"SOAP Fault: {fault}")
            raise
        except Exception as err:
            print(f"Error: {err}")
            raise



def main():
    """Main entry point for the script."""
    # Get credentials from environment variables or replace with actual values
    username = os.getenv("TEBRA_USERNAME", "reba.magier@canvasmedical.com")
    password = os.getenv("TEBRA_PASSWORD", "jyd@ryn*dcd!EKX0wan")
    customer_key = os.getenv("TEBRA_CUSTOMER_KEY", "z87ed45rg62f")
    print(username, customer_key)

    print("\nFetching practices from Tebra...")
    client = TebraSoapClient(username, password, customer_key)
    practices = client.get_tebra_data(operation="Practice", filters=DEFAULT_PRACTICE_NAME_FILTERS, fields=PRACTICE_FIELDS_TO_RETURN)
    practice_id_filters = [
        {"PracticeID": int(practice["ID"])}
        for practice in practices
        if practice.get("ID") is not None
    ]
    practice_name_filters = [
        {"PracticeName": practice["PracticeName"]}
        for practice in practices
        if practice.get("PracticeName")
    ]
    appointment_reason_requests = [
        {
            "extra_request": {"PracticeId": int(practice["ID"])}
        }
        for practice in practices
        if practice.get("ID") is not None
    ]
    print(practice_id_filters)

    print("\nFetching patients from Tebra...")
    patients = client.get_tebra_data(operation="Patient", filters=practice_id_filters, fields=PATIENT_FIELDS_TO_RETURN)


    print("\nFetching appointments from Tebra...")
    appointments = client.get_tebra_data(operation="Appointment", filters=practice_name_filters, fields=APPOINTMENT_FIELDS_TO_RETURN)

    print(f"\nFetching appointment reasons from Tebra...")
    appointment_reasons = client.get_tebra_data(operation="AppointmentReason", filters=appointment_reason_requests)

    print(f"\nFetching charges from Tebra...")
    charges = client.get_tebra_data(operation="Charge", filters=practice_name_filters, fields=CHARGE_FIELDS_TO_RETURN)

    # print(f"\nFetching encounters from Tebra...")
    # encounter_id_filters = [{"EncounterID": int(charge["EncounterID"])} for charge in charges if charge.get("EncounterID") is not None]
    # encounters = client.get_tebra_data(operation="EncounterDetail", filters=encounter_id_filters, fields=ENCOUNTER_FIELDS_TO_RETURN, special_data_name="EncounterDetailsData")

    print(f"\nFetching payments from Tebra...")
    payments = client.get_tebra_data(operation="Payment")

    print(f"\nFetching procedure codes from Tebra...")
    procedure_codes = client.get_tebra_data(operation="ProcedureCode")

    print(f"\nFetching providers from Tebra...")
    providers = client.get_tebra_data(operation="Provider", filters=practice_name_filters)

    print(f"\nFetching service locations from Tebra...")
    service_locations = client.get_tebra_data(operation="ServiceLocation", filters=practice_id_filters)

    print(f"\nFetching transactions from Tebra...")
    transactions = client.get_tebra_data(operation="Transaction", filters=practice_name_filters)

if __name__ == "__main__":
    main()

