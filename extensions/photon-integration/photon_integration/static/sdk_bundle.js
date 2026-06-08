{% verbatim %}
/**
 * Bundled by jsDelivr using Rollup v2.79.2 and Terser v5.48.0.
 * Original file: /npm/@photonhealth/sdk@1.3.4/dist/lib.mjs
 *
 * Do NOT use SRI with dynamically generated files! More information: https://www.jsdelivr.com/using-sri-with-dynamic-files
 */
import{__awaiter as e,__rest as t}from"/npm/tslib@2.7.0/+esm";import{Auth0Client as i}from"/npm/@auth0/auth0-spa-js@2.1.3/+esm";import{gql as n,ApolloClient as r,HttpLink as a,InMemoryCache as s}from"/npm/@apollo/client@3.11.8/+esm";import{setContext as o}from"/npm/@apollo/client@3.11.8/link/context/index.js/+esm";const d=/[?&]code=[^&]+/,l=/[?&]state=[^&]+/,c=/[?&]error=[^&]+/;class u{constructor({authentication:t,organization:i,audience:n="https://api.photon.health",connection:r}){this._getAccessToken=({audience:t}={audience:this.audience},i=!1)=>e(this,void 0,void 0,function*(){const e={authorizationParams:Object.assign({audience:t||this.audience||void 0},this.organization?{organization:this.organization}:{})};let n;try{n=yield this.authentication.getTokenSilently(e)}catch(t){t.message.includes("Consent required")&&(n=yield this.authentication.getTokenWithPopup(e))}if(!n){if(yield this.authentication.loginWithRedirect(e),i)throw new Error;return yield this._getAccessToken({audience:t},!0)}return n}),this.authentication=t,this.organization=i,this.audience=n,this.connection=r}login({organizationId:t,invitation:i,appState:n}){return e(this,void 0,void 0,function*(){const e=Object.assign({authorizationParams:Object.assign(Object.assign(Object.assign(Object.assign({},this.audience?{audience:this.audience}:{}),this.connection?{connection:this.connection}:{}),t||this.organization?{organization:t||this.organization}:{}),i?{invitation:i}:{})},n?{appState:n}:{});return this.authentication.loginWithRedirect(e)})}logout({returnTo:t,federated:i=!1}){return e(this,void 0,void 0,function*(){const e={logoutParams:Object.assign(Object.assign({},t?{returnTo:t}:{}),i?{federated:i}:{})};return this.authentication.logout(e)})}hasAuthParams(e=window.location.search){return(d.test(e)||c.test(e))&&l.test(e)}getAccessToken({audience:t}={audience:this.audience}){return e(this,void 0,void 0,function*(){return yield this._getAccessToken({audience:null!=t?t:this.audience})})}getAccessTokenWithConsent({audience:t}={audience:this.audience}){return e(this,void 0,void 0,function*(){const e={authorizationParams:Object.assign({audience:t||this.audience||void 0},this.organization?{organization:this.organization}:{})};return this.authentication.getTokenWithPopup(e)})}checkSession(){return e(this,void 0,void 0,function*(){const e={authorizationParams:Object.assign({audience:this.audience||void 0},this.organization?{organization:this.organization}:{})};return this.authentication.checkSession(e)})}handleRedirect(t){return e(this,void 0,void 0,function*(){try{return this.authentication.handleRedirectCallback(t)}catch(e){console.error(e)}})}getUser(){return e(this,void 0,void 0,function*(){return this.authentication.getUser()})}isAuthenticated(){return e(this,void 0,void 0,function*(){try{return yield this.authentication.checkSession(),yield this.authentication.isAuthenticated()}catch(e){return!1}})}}const p=n`
  fragment OrganizationFields on Organization {
    id
    name
  }
`,h=n`
  fragment PatientFields on Patient {
    id
    externalId
    name {
      full
    }
    dateOfBirth
    sex
    gender
    email
    phone
    address {
      name {
        full
      }
      city
      country
      postalCode
      state
      street1
      street2
    }
  }
`,m=n`
  fragment AllergenFields on Allergen {
    id
    name
    rxcui
  }
`,g=n`
  fragment CatalogFields on Catalog {
    id
    name
  }
`,$=n`
  fragment MedicationFields on Medication {
    id
    name
    form
    schedule
    controlled
  }
`,f=n`
  fragment SearchMedicationFields on SearchMedication {
    id
    name
  }
`,I=n`
  fragment MedicalEquipmentFields on MedicalEquipment {
    id
    name
  }
`,y=n`
  fragment CatalogTreatmentFields on Catalog {
    treatments {
      id
      name
    }
  }
`,P=n`
  fragment DispenseUnitFields on DispenseUnit {
    name
  }
`,b=n`
  fragment FillPrescriptionFields on Fill {
    id
    state
    requestedAt
    filledAt
    order {
      id
      createdAt
      state
      fulfillment {
        state
      }
      pharmacy {
        id
        name
        address {
          street1
          street2
          city
          state
          postalCode
        }
      }
    }
  }
`,O=n`
  ${b}
  fragment PrescriptionFields on Prescription {
    id
    externalId
    fills {
      ...FillPrescriptionFields
    }
    prescriber {
      id
      name {
        full
      }
    }
    patient {
      id
      name {
        full
      }
    }
    state
    treatment {
      id
      name
    }
    dispenseAsWritten
    dispenseQuantity
    dispenseUnit
    fillsAllowed
    fillsRemaining
    daysSupply
    instructions
    notes
    effectiveDate
    expirationDate
    writtenAt
  }
`,v=n`
  fragment FillFields on Fill {
    id
    prescription {
      id
    }
    treatment {
      name
    }
    state
    requestedAt
    filledAt
  }
`,F=n`
  ${h}
  ${v}
  fragment OrderFields on Order {
    id
    externalId
    state
    fills {
      ...FillFields
    }
    patient {
      ...PatientFields
    }
    pharmacy {
      id
      name
      phone
      address {
        city
        country
        postalCode
        state
        street1
        street2
      }
    }
    fulfillment {
      type
      state
      carrier
      trackingNumber
    }
    createdAt
  }
`,S=n`
  fragment WebhookFields on WebhookConfig {
    id
    name
    filters
    url
  }
`,D=n`
  fragment ClientFields on Client {
    id
    name
    secret
    appType
  }
`,A=n`
  fragment PharmacyFields on Pharmacy {
    id
    NPI
    NCPDP
    name
    fulfillmentTypes
    address {
      city
      country
      postalCode
      state
      street1
      street2
    }
  }
`,C=n`
  fragment PrescriptionTemplateFields on PrescriptionTemplate {
    id
    daysSupply
    dispenseAsWritten
    dispenseQuantity
    dispenseUnit
    instructions
    notes
    fillsAllowed
    treatment {
      id
      name
    }
    isPrivate
  }
`,j=Object.freeze(Object.defineProperty({__proto__:null,ORGANIZATION_FIELDS:p,PATIENT_FIELDS:h,ALLERGEN_FIELDS:m,CATALOG_FIELDS:g,MEDICATION_FIELDS:$,SEARCH_MEDICATION_FIELDS:f,MEDICAL_EQUIPMENT_FIELDS:I,CATALOG_TREATMENT_FIELDS:y,DISPENSE_UNIT_FIELDS:P,FILL_PRESCRIPTION_FIELDS:b,PRESCRIPTION_FIELDS:O,FILL_FIELDS:v,ORDER_FIELDS:F,WEBHOOK_CONFIG_FIELDS:S,CLIENT_FIELDS:D,PHARMACY_FIELDS:A,PRESCRIPTION_TEMPLATE_FIELDS:C},Symbol.toStringTag,{value:"Module"}));function E(t,i,n={},r="network-only"){return e(this,void 0,void 0,function*(){const e=yield t.query({query:i,variables:n,fetchPolicy:r});return Object.assign(Object.assign({},e),{refetch:e=>t.query({query:i,variables:Object.assign(n,e)}),fetchMore:({after:e,first:r})=>t.query({query:i,variables:Object.assign(n,{after:e,first:r})})})})}function T(e,t){return({variables:i,refetchQueries:n,awaitRefetchQueries:r=!1})=>e.mutate({mutation:t,refetchQueries:n,awaitRefetchQueries:r,variables:i})}const k={tau:"https://app.boson.health",boson:"https://app.boson.health",neutron:"https://app.neutron.health",photon:"https://app.photon.health"},w={tau:"https://api.boson.health",boson:"https://api.boson.health",neutron:"https://api.neutron.health",photon:"https://api.photon.health"},q={tau:"http://clinical-api.tau.health:8080",boson:"https://clinical-api.boson.health",neutron:"https://clinical-api.neutron.health",photon:"https://clinical-api.photon.health"};class z{constructor(e){this.apollo=e}getCatalogs({fragment:t}={fragment:{CatalogFields:g}}){return e(this,void 0,void 0,function*(){t||(t={CatalogFields:g});const[e,i]=Object.entries(t)[0],r=n`
      ${i}
      query catalogs {
        catalogs {
          ...${e}
        }
      }
    `;return E(this.apollo,r)})}getCatalog({id:t,fragment:i}={id:"",fragment:{CatalogFields:g}}){return e(this,void 0,void 0,function*(){i||(i={CatalogFields:g});const[e,r]=Object.entries(i)[0],a=n`
      ${r}
      query catalog($id: ID) {
        catalog(id: $id) {
          ...${e}
        }
      }
    `;return E(this.apollo,a,{id:t})})}addToCatalog({fragment:e}){e||(e={MedicationFields:$});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation addToCatalog(
        $catalogId: ID!
        $treatmentId: ID!
      ) {
        addToCatalog(
          catalogId: $catalogId
          treatmentId: $treatmentId
        ) {
          ...${t}
        }
      }
    `;return T(this.apollo,r)}removeFromCatalog({fragment:e}){e||(e={MedicationFields:$});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation removeFromCatalog(
        $catalogId: ID!
        $treatmentId: ID!
      ) {
        removeFromCatalog(
          catalogId: $catalogId
          treatmentId: $treatmentId
        ) {
          ...${t}
        }
      }
    `;return T(this.apollo,r)}}class R{constructor(e){this.apollo=e}getMedications({filter:t,after:i,first:r,fragment:a}={fragment:{MedicationFields:$}}){return e(this,void 0,void 0,function*(){a||(a={MedicationFields:$});const[e,s]=Object.entries(a)[0],o=n`
      ${s}
      query medications($filter: MedicationFilter, $after: ID, $first: Int) {
        medications(filter: $filter, after: $after, first: $first) {
          ...${e}
    }
  }
    `;return E(this.apollo,o,{filter:t,after:i,first:r})})}}class M{constructor(e){this.apollo=e}getMedicalEquipment({name:t,after:i,first:r,fragment:a}={fragment:{MedicalEquipmentFields:I}}){return e(this,void 0,void 0,function*(){a||(a={MedicalEquipmentFields:I});const[e,s]=Object.entries(a)[0],o=n`
      ${s}
      query medicalEquipment($name: String, $after: ID, $first: Int) {
        medicalEquipment(name: $name, after: $after, first: $first) {
          ...${e}
    }
  }
    `;return E(this.apollo,o,{name:t,after:i,first:r})})}}class N{constructor(e){this.apollo=e}getOrders({patientId:t,patientName:i,after:r,first:a,fragment:s}={first:25,fragment:{OrderFields:F}}){return e(this,void 0,void 0,function*(){a||(a=25),s||(s={OrderFields:F});const[e,o]=Object.entries(s)[0],d=n`
        ${o}
        query orders(
          $patientId: ID
          $patientName: String
          $after: ID
          $first: Int
      ) {
          orders(
              filter: {
                  patientId: $patientId
                  patientName: $patientName
              }
              after: $after
              first: $first
          ) {
              ...${e}
          }
        }
      `;return E(this.apollo,d,{patientId:t,patientName:i,after:r,first:a})})}getOrder({id:t,fragment:i}={id:"",fragment:{OrderFields:F}}){return e(this,void 0,void 0,function*(){i||(i={OrderFields:F});const[e,r]=Object.entries(i)[0],a=n`
        ${r}
        query order($id: ID!) {
          order(id: $id) {
            ...${e}
          }
        }
      `;return E(this.apollo,a,{id:t})})}createOrder({fragment:e}){e||(e={OrderFields:F});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation createOrder(
        $externalId: ID
        $patientId: ID!
        $fills: [FillInput!]!
        $address: AddressInput!
        $pharmacyId: ID!
      ) {
        createOrder(
          externalId: $externalId
          patientId: $patientId
          fills: $fills
          address: $address
          pharmacyId: $pharmacyId
        ) {
          ...${t}
        }
      }
    `;return T(this.apollo,r)}}class x{constructor(e){this.apollo=e}getPatient({id:t,fragment:i}={id:"",fragment:{PatientFields:h}}){return e(this,void 0,void 0,function*(){i||(i={PatientFields:h});const[e,r]=Object.entries(i)[0],a=n`
      ${r}
      query patient($id: ID!) {
        patient(id: $id) {
          ...${e}
        }
      }
    `;return E(this.apollo,a,{id:t})})}getPatients({after:t,first:i,name:r,fragment:a}={first:25,fragment:{PatientFields:h}}){return e(this,void 0,void 0,function*(){a||(a={PatientFields:h}),i||(i=25);const[e,s]=Object.entries(a)[0],o=n`
      ${s}
      query patients($after: ID, $name: String, $first: Int) {
        patients(after: $after, first: $first, filter: { name: $name }) {
          ...${e}
        }
      }
    `;return E(this.apollo,o,{after:t,name:r,first:i})})}createPatient({fragment:e}){e||(e={PatientFields:h});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation createPatient(
        $externalId: ID
        $name: NameInput!
        $dateOfBirth: AWSDate!
        $sex: SexType!
        $gender: String
        $email: AWSEmail
        $phone: AWSPhone!
        $address: AddressInput
        $allergies: [AllergenInput]
        $medicationHistory: [MedHistoryInput]
        $preferredPharmacies: [ID]
      ) {
        createPatient(
          externalId: $externalId
          name: $name
          dateOfBirth: $dateOfBirth
          sex: $sex
          gender: $gender
          address: $address
          email: $email
          phone: $phone
          allergies: $allergies
          medicationHistory: $medicationHistory
          preferredPharmacies: $preferredPharmacies
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}updatePatient({fragment:e}){e||(e={PatientFields:h});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation updatePatient(
        $id: ID!
        $externalId: ID
        $name: NameInput
        $dateOfBirth: AWSDate
        $sex: SexType
        $gender: String
        $email: AWSEmail
        $phone: AWSPhone
        $allergies: [AllergenInput]
        $medicationHistory: [MedHistoryInput]
        $address: AddressInput
        $preferredPharmacies: [ID]
      ) {
        updatePatient(
          id: $id
          externalId: $externalId
          name: $name
          dateOfBirth: $dateOfBirth
          sex: $sex
          gender: $gender
          email: $email
          phone: $phone
          allergies: $allergies
          medicationHistory: $medicationHistory
          address: $address,
          preferredPharmacies: $preferredPharmacies
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}removePatientPreferredPharmacy({fragment:e}){e||(e={PatientFields:h});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation removePatientPreferredPharmacy(
        $patientId: ID!
        $pharmacyId: ID!
      ) {
        removePatientPreferredPharmacy(
          patientId: $patientId
          pharmacyId: $pharmacyId
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}removePatientAllergy({fragment:e}){e||(e={PatientFields:h});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation removePatientAllergy(
        $id: ID!
        $allergenId: ID!
      ) {
        updatePatient(
          id: $id
          allergenId: $allergenId
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}}class L{constructor(e){this.apollo=e}getPharmacies({name:t,location:i,type:r,after:a,first:s,fragment:o}={first:100,fragment:{PharmacyFields:A}}){return e(this,void 0,void 0,function*(){s||(s=100),o||(o={PharmacyFields:A});const[e,d]=Object.entries(o)[0],l=n`
      ${d}
      query pharmacies($name: String, $location: LatLongSearch, $type: FulfillmentType, $after: Int, $first: Int) {
        pharmacies(name: $name, location: $location, type: $type, after: $after, first: $first) {
          ...${e}
        }
      }
    `;return E(this.apollo,l,{name:t,location:i,type:r,after:a,first:s})})}getPharmacy({id:t,fragment:i}={id:"",fragment:{PharmacyFields:A}}){return e(this,void 0,void 0,function*(){i||(i={PharmacyFields:A});const[e,r]=Object.entries(i)[0],a=n`
          ${r}
          query pharmacy($id: ID!) {
            pharmacy(id: $id) {
              ...${e}
            }
          }
        `;return E(this.apollo,a,{id:t})})}}class U{constructor(e){this.apollo=e}getPrescriptions({patientId:t,patientName:i,prescriberId:r,state:a,after:s,first:o,fragment:d}={first:25,fragment:{PrescriptionFields:O}}){return e(this,void 0,void 0,function*(){d||(d={PrescriptionFields:O}),o||(o=25);const[e,l]=Object.entries(d)[0],c=n`
          ${l}
          query prescriptions(
            $patientId: ID
            $patientName: String
            $prescriberId: ID
            $state: PrescriptionState
            $after: ID
            $first: Int
        ) {
            prescriptions(
                filter: {
                    patientId: $patientId
                    patientName: $patientName
                    prescriberId: $prescriberId
                    state: $state
                }
                after: $after
                first: $first
            ) {
                ...${e}
            }
          }
        `;return E(this.apollo,c,{patientId:t,patientName:i,prescriberId:r,state:a,after:s,first:o})})}getPrescription({id:t,fragment:i}={id:"",fragment:{PrescriptionFields:O}}){return e(this,void 0,void 0,function*(){i||(i={PrescriptionFields:O});const[e,r]=Object.entries(i)[0],a=n`
          ${r}
          query prescription($id: ID!) {
            prescription(id: $id) {
              ...${e}
            }
          }
        `;return E(this.apollo,a,{id:t})})}getDispenseUnits({fragment:t}={fragment:{DispenseUnitFields:P}}){return e(this,void 0,void 0,function*(){t||(t={DispenseUnitFields:P});const[e,i]=Object.entries(t)[0],r=n`
          ${i}
          query dispenseUnits {
            dispenseUnits {
              ...${e}
            }
          }
        `;return E(this.apollo,r,{})})}createPrescription({fragment:e}){e||(e={PrescriptionFields:O});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation createPrescription(
        $externalId: ID
        $patientId: ID!
        $treatmentId: ID!
        $dispenseAsWritten: Boolean
        $dispenseQuantity: Float!
        $dispenseUnit: String!
        $fillsAllowed: Int!
        $daysSupply: Int
        $instructions: String!
        $notes: String
        $effectiveDate: AWSDate
        $diagnoses: [ID]
      ) {
        createPrescription(
          externalId: $externalId
          patientId: $patientId
          treatmentId: $treatmentId
          dispenseAsWritten: $dispenseAsWritten
          dispenseQuantity: $dispenseQuantity
          dispenseUnit: $dispenseUnit
          fillsAllowed: $fillsAllowed
          daysSupply: $daysSupply
          instructions: $instructions
          notes: $notes
          effectiveDate: $effectiveDate
          diagnoses: $diagnoses
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}createPrescriptions({fragment:e}){e||(e={PrescriptionFields:O});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation createPrescriptions(
        $prescriptions: [PrescriptionInput]!
      ) {
        createPrescriptions(
          prescriptions: $prescriptions
        ) {
          ...${t}
        }
      }`;return T(this.apollo,r)}}class W{constructor(e){this.apollo=e}getAllergens({fragment:t,filter:i}={fragment:{AllergenFields:m}}){return e(this,void 0,void 0,function*(){t||(t={AllergenFields:m});const[e,r]=Object.entries(t)[0],a=n`
        ${r}
        query allergens($filter: AllergenFilter) {
            allergens(filter: $filter) {
                ...${e}
            }
        }
      `;return E(this.apollo,a,{filter:i})})}}class _{constructor(e){this.apollo=e}createPrescriptionTemplate({fragment:e}){e||(e={PrescriptionTemplateFields:C});const[t,i]=Object.entries(e)[0],r=n`
        ${i}
        mutation createPrescriptionTemplate(
          $catalogId: ID!,
          $treatmentId: ID!,
          $dispenseAsWritten: Boolean,
          $dispenseQuantity: Float,
          $dispenseUnit: String,
          $fillsAllowed: Int,
          $daysSupply: Int,
          $instructions: String,
          $notes: String,
          $name: String,
          $isPrivate: Boolean
        ) {
          createPrescriptionTemplate(
            catalogId: $catalogId
            treatmentId: $treatmentId
            dispenseAsWritten: $dispenseAsWritten
            dispenseQuantity: $dispenseQuantity
            dispenseUnit: $dispenseUnit
            fillsAllowed: $fillsAllowed
            daysSupply: $daysSupply
            instructions: $instructions
            notes: $notes
            name: $name
            isPrivate: $isPrivate
        ) {
            ...${t}
        }
      }
      `;return T(this.apollo,r)}updatePrescriptionTemplate({fragment:e}){e||(e={PrescriptionTemplateFields:C});const[t,i]=Object.entries(e)[0],r=n`
        ${i}
        mutation updatePrescriptionTemplate(
          $catalogId: ID!,
          $templateId: ID!,
          $dispenseAsWritten: Boolean,
          $dispenseQuantity: Float,
          $dispenseUnit: String,
          $fillsAllowed: Int,
          $daysSupply: Int,
          $instructions: String,
          $notes: String,
          $name: String
        ) {
          updatePrescriptionTemplate(
            catalogId: $catalogId
            templateId: $templateId
            dispenseAsWritten: $dispenseAsWritten
            dispenseQuantity: $dispenseQuantity
            dispenseUnit: $dispenseUnit
            fillsAllowed: $fillsAllowed
            daysSupply: $daysSupply
            instructions: $instructions
            notes: $notes
            name: $name
        ) {
            ...${t}
        }
      }
      `;return T(this.apollo,r)}deletePrescriptionTemplate({fragment:e}){e||(e={PrescriptionTemplateFields:C});const[t,i]=Object.entries(e)[0],r=n`
        ${i}
        mutation deletePrescriptionTemplate(
          $catalogId: ID!,
          $templateId: ID!
        ) {
          deletePrescriptionTemplate(
            catalogId: $catalogId
            templateId: $templateId
        ) {
            ...${t}
        }
      }
      `;return T(this.apollo,r)}}class H{constructor(e){this.apollo=e}getConcepts({name:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={SearchMedicationFields:f});const[e,r]=Object.entries(i)[0],a=n`
        ${r}
        query medicationConcepts($name: String!) {
          medicationConcepts(name: $name) {
            ...${e}
      }
    }
      `;return E(this.apollo,a,{name:t})})}getStrengths({id:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={SearchMedicationFields:f});const[e,r]=Object.entries(i)[0],a=n`
          ${r}
          query medicationStrengths($id: String!) {
            medicationStrengths(id: $id) {
              ...${e}
        }
      }
        `;return E(this.apollo,a,{id:t})})}getRoutes({id:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={SearchMedicationFields:f});const[e,r]=Object.entries(i)[0],a=n`
              ${r}
              query medicationRoutes($id: String!) {
                medicationRoutes(id: $id) {
                  ...${e}
            }
          }
            `;return E(this.apollo,a,{id:t})})}getForms({id:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={MedicationFields:$});const[e,r]=Object.entries(i)[0],a=n`
              ${r}
              query medicationForms($id: String!) {
                medicationForms(id: $id) {
                  ...${e}
            }
          }
            `;return E(this.apollo,a,{id:t})})}getProducts({id:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={MedicationFields:$});const[e,r]=Object.entries(i)[0],a=n`
                  ${r}
                  query medicationProducts($id: String!) {
                    medicationProducts(id: $id) {
                      ...${e}
                }
              }
                `;return E(this.apollo,a,{id:t})})}getPackages({id:t,fragment:i}){return e(this,void 0,void 0,function*(){i||(i={MedicationFields:$});const[e,r]=Object.entries(i)[0],a=n`
                  ${r}
                  query medicationPackages($id: String!) {
                    medicationPackages(id: $id) {
                      ...${e}
                }
              }
                `;return E(this.apollo,a,{id:t})})}}class Q{constructor(e){this.catalog=new z(e),this.medication=new R(e),this.medicalEquipment=new M(e),this.searchMedication=new H(e),this.order=new N(e),this.patient=new x(e),this.pharmacy=new L(e),this.prescription=new U(e),this.allergens=new W(e),this.prescriptionTemplate=new _(e)}}class B{constructor(e){this.apollo=e}getClients({fragment:t}={fragment:{ClientFields:D}}){return e(this,void 0,void 0,function*(){const[e,i]=Object.entries(t)[0],r=n`
          ${i}
          query clients {
            clients {
              ...${e}
            }
          }
        `;return E(this.apollo,r)})}rotateSecret({fragment:e}){e||(e={ClientFields:D});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation rotateSecret(
        $id: ID!
      ) {
        rotateSecret(id: $id) {
          ...${t}
        }
      }
    `;return T(this.apollo,r)}}class G{constructor(e){this.apollo=e}getOrganization({fragment:t}={fragment:{OrganizationFields:p}}){return e(this,void 0,void 0,function*(){t||(t={OrganizationFields:p});const[e,i]=Object.entries(t)[0],r=n`
      ${i}
      query organization {
        organization {
          ...${e}
        }
      }
    `;return E(this.apollo,r)})}getOrganizations({fragment:t}={fragment:{OrganizationFields:p}}){return e(this,void 0,void 0,function*(){t||(t={OrganizationFields:p});const[e,i]=Object.entries(t)[0],r=n`
      ${i}
      query organizations {
        organizations {
          ...${e}
        }
      }
    `;return E(this.apollo,r)})}}class V{constructor(e){this.apollo=e}getWebhooks({fragment:t}={fragment:{WebhookFields:S}}){return e(this,void 0,void 0,function*(){t||(t={WebhookFields:S});const[e,i]=Object.entries(t)[0],r=n`
      ${i}
      query webhooks {
        webhooks {
          ...${e}
        }
      }
    `;return E(this.apollo,r)})}createWebhook({fragment:e}){e||(e={WebhookFields:S});const[t,i]=Object.entries(e)[0],r=n`
      ${i}
      mutation createWebhook(
        $name: String
        $filters: [String]
        $sharedSecret: String
        $url: String!
      ) {
        createWebhookConfig(name: $name, filters: $filters, sharedSecret: $sharedSecret, url: $url) {
          ...${t}
        }
      }`;return T(this.apollo,r)}deleteWebhook(){const e=n`
      mutation deleteWebhookConfig($id: String!) {
        deleteWebhookConfig(id: $id)
      }
    `;return T(this.apollo,e)}}class K{constructor(e){this.client=new B(e),this.organization=new G(e),this.webhook=new V(e)}}var X,Y,Z,J,ee,te,ie,ne,re,ae,se,oe,de,le,ce,ue,pe,he,me,ge,$e;(Y=X||(X={})).Drug="DRUG",Y.Package="PACKAGE",Y.Product="PRODUCT",(Z||(Z={})).Icd10="ICD10",(ee=J||(J={})).Canceled="CANCELED",ee.New="NEW",ee.Scheduled="SCHEDULED",ee.Sent="SENT",(ie=te||(te={})).MailOrder="MAIL_ORDER",ie.PickUp="PICK_UP",(re=ne||(ne={})).Otc="OTC",re.Rx="RX",(se=ae||(ae={})).Canceled="CANCELED",se.Completed="COMPLETED",se.Error="ERROR",se.Pending="PENDING",se.Placed="PLACED",se.Routing="ROUTING",(de=oe||(oe={})).Pharmacy="PHARMACY",de.Prescriber="PRESCRIBER",(ce=le||(le={})).Active="ACTIVE",ce.Depleted="DEPLETED",ce.Expired="EXPIRED",ce.Canceled="CANCELED",(pe=ue||(ue={})).I="I",pe.Ii="II",pe.Iii="III",pe.Iv="IV",pe.V="V",(me=he||(he={})).Concept="CONCEPT",me.Form="FORM",me.Route="ROUTE",me.Strength="STRENGTH",($e=ge||(ge={})).Female="FEMALE",$e.Male="MALE",$e.Unknown="UNKNOWN";const fe=Object.freeze(Object.defineProperty({__proto__:null,get ConceptType(){return X},get DiagnosisType(){return Z},get FillState(){return J},get FulfillmentType(){return te},get MedicationType(){return ne},get OrderState(){return ae},get OrgType(){return oe},get PrescriptionState(){return le},get ScheduleType(){return ue},get SearchMedicationType(){return he},get SexType(){return ge}},Symbol.toStringTag,{value:"Module"})),Ie={name:"@photonhealth/sdk",version:"1.3.4",main:"dist/lib.js",scripts:{build:"npx nx run sdk:build",docs:'find src -name "*.ts" | xargs npx typedoc --out docs',prepublishOnly:"npm run build"},publishConfig:{access:"public"},keywords:[],author:"",license:"ISC",devDependencies:{"@babel/core":"^7.18.9","@babel/preset-env":"^7.18.9","@rollup/plugin-typescript":"^8.3.4","@types/node":"^18.6.3",path:"^0.12.7",rimraf:"^3.0.2",tslib:"^2.4.0",typedoc:"^0.23.10"},dependencies:{"@apollo/client":"^3.6.9","@auth0/auth0-spa-js":"^2.1.3","@nanostores/react":"^0.4.1",nanostores:"^0.7.4"},exports:{".":{import:"./dist/lib.mjs",require:"./dist/lib.js"}},types:"./dist/lib.d.ts",repository:{type:"git",url:"git+https://github.com/Photon-Health/photon-sdk-js.git"},bugs:{url:"https://github.com/Photon-Health/photon-sdk-js/issues"},homepage:"https://github.com/Photon-Health/photon-sdk-js#readme",description:"",gitHead:"af370de34a8764638dbdc4bd5092f62db2eefee2"};var ye;const Pe=null!==(ye=null==Ie?void 0:Ie.version)&&void 0!==ye?ye:"unknown";class be{constructor({domain:e,clientId:t,redirectURI:n,organization:r,env:a="photon",audience:s,connection:o,uri:d,developmentMode:l=!1},c){this.audience=s||w[a],this.uri=d||`${w[a]}/graphql`,this.clinicalUrl=d?function(e){const t=Object.keys(k).find(t=>e.toLowerCase().includes(t));return k[t||"photon"]}(d):k[a],this.clinicalApiUri=`${q[a]}/graphql`,l&&(this.audience=w.neutron,this.uri=`${w.neutron}/graphql`,this.clinicalApiUri=`${q.neutron}/graphql`);const p={domain:e||(l?"auth.neutron.health":"auth.photon.health"),clientId:t,cacheLocation:"localstorage",useRefreshTokens:!0,useRefreshTokensFallback:!0,authorizationParams:Object.assign({redirect_uri:n,audience:this.audience},o?{connection:o}:{})};this.auth0Client=new i(p),this.organization=r,this.authentication=new u(Object.assign({authentication:this.auth0Client,organization:this.organization,audience:this.audience},o?{connection:o}:{})),this.apollo=this.constructApolloClient({elementsVersion:c,isServices:!1}),this.apolloClinical=this.constructApolloClient({elementsVersion:c,isServices:!0}),this.clinical=new Q(this.apollo),this.management=new K(this.apollo)}constructApolloClient({elementsVersion:i,isServices:n}={isServices:!1}){return new r({link:o((r,a)=>e(this,void 0,void 0,function*(){var{headers:e}=a,r=t(a,["headers"]);const s=yield this.authentication.getAccessToken(),o=Object.assign(Object.assign(Object.assign({},e),{"x-photon-sdk-version":Pe}),i?{"x-photon-elements-version":i}:{});return s?Object.assign(Object.assign({},r),{headers:n?Object.assign(Object.assign({},o),{"x-photon-auth-token":s,"x-photon-auth-token-type":"auth0"}):Object.assign(Object.assign({},o),{authorization:s})}):Object.assign({headers:o},r)})).concat(new a({uri:n?this.clinicalApiUri:this.uri})),defaultOptions:{query:{fetchPolicy:"cache-first",errorPolicy:"all"},mutate:{onQueryUpdated:Oe}},cache:new s({typePolicies:{Patient:{fields:{name:{merge:(e,t,{mergeObjects:i})=>i(e,t)},address:{merge:(e,t,{mergeObjects:i})=>i(e,t)}}},User:{fields:{name:{merge:(e,t,{mergeObjects:i})=>i(e,t)},address:{merge:(e,t,{mergeObjects:i})=>i(e,t)}}}}})})}setOrganization(e){return this.organization=e,this.authentication=new u({authentication:this.auth0Client,organization:e,audience:this.audience}),this}clearOrganization(){return this.organization=void 0,this.authentication=new u({authentication:this.auth0Client,organization:void 0,audience:this.audience}),this.authentication.login({}),this}}const Oe=t=>e(void 0,void 0,void 0,function*(){var e;yield(e=1e3,new Promise(t=>setTimeout(t,e))),t.refetch()});export{be as PhotonClient,j as fragments,fe as types};export default null;
//# sourceMappingURL=/sm/6f79432eba242461e0b0ed55f99e65a57dad130716624f139b307063b18b4e99.map{% endverbatim %}
