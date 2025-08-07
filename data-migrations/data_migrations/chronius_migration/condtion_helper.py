from data_migrations.utils import fetch_from_json
import csv

_map = {
    "A047": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "A0472",
            "display": "Enterocolitis due to Clostridium difficile, not specified as recurrent"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "A0471",
            "display": "Enterocolitis due to Clostridium difficile, recurrent"
        }
    ],
    "A6922": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "A6922",
        "display": "Other neurologic disorders in Lyme disease"
    },
    "B0222": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "B0222",
        "display": "Postherpetic trigeminal neuralgia"
    },
    "B27": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2700",
            "display": "Gammaherpesviral mononucleosis without complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2799",
            "display": "Infectious mononucleosis, unspecified with other complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2790",
            "display": "Infectious mononucleosis, unspecified without complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2710",
            "display": "Cytomegaloviral mononucleosis without complications"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2711",
            "display": "Cytomegaloviral mononucleosis with polyneuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2712",
            "display": "Cytomegaloviral mononucleosis with meningitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2719",
            "display": "Cytomegaloviral mononucleosis with other complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2780",
            "display": "Other infectious mononucleosis without complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2781",
            "display": "Other infectious mononucleosis with polyneuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2782",
            "display": "Other infectious mononucleosis with meningitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2789",
            "display": "Other infectious mononucleosis with other complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2791",
            "display": "Infectious mononucleosis, unspecified with polyneuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2792",
            "display": "Infectious mononucleosis, unspecified with meningitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2702",
            "display": "Gammaherpesviral mononucleosis with meningitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2701",
            "display": "Gammaherpesviral mononucleosis with polyneuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2709",
            "display": "Gammaherpesviral mononucleosis with other complications"
        }
    ],
    "B279": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2799",
            "display": "Infectious mononucleosis, unspecified with other complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2790",
            "display": "Infectious mononucleosis, unspecified without complication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2791",
            "display": "Infectious mononucleosis, unspecified with polyneuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "B2792",
            "display": "Infectious mononucleosis, unspecified with meningitis"
        }
    ],
    "B373": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "B373",
        "display": "Candidiasis of vulva and vagina"
    },
    "B379": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "B379",
        "display": "Candidiasis, unspecified"
    },
    "D039": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "D039",
        "display": "Melanoma in situ, unspecified"
    },
    "D50": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D501",
            "display": "Sideropenic dysphagia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D500",
            "display": "Iron deficiency anemia secondary to blood loss (chronic)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D508",
            "display": "Other iron deficiency anemias"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D509",
            "display": "Iron deficiency anemia, unspecified"
        }
    ],
    "D51": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D511",
            "display": "Vitamin B12 deficiency anemia due to selective vitamin B12 malabsorption with proteinuria"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D513",
            "display": "Other dietary vitamin B12 deficiency anemia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D519",
            "display": "Vitamin B12 deficiency anemia, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D518",
            "display": "Other vitamin B12 deficiency anemias"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D510",
            "display": "Vitamin B12 deficiency anemia due to intrinsic factor deficiency"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D512",
            "display": "Transcobalamin II deficiency"
        }
    ],
    "D894": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8940",
            "display": "Mast cell activation, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8941",
            "display": "Monoclonal mast cell activation syndrome"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8942",
            "display": "Idiopathic mast cell activation syndrome"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8943",
            "display": "Secondary mast cell activation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8944",
            "display": "Hereditary alpha tryptasemia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "D8949",
            "display": "Other mast cell activation disorder"
        }
    ],
    "D8949": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "D8949",
        "display": "Other mast cell activation disorder"
    },
    "E281": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "E281",
        "display": "Androgen excess"
    },
    "E721": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E7210",
            "display": "Disorders of sulfur-bearing amino-acid metabolism, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E7211",
            "display": "Homocystinuria"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E7212",
            "display": "Methylenetetrahydrofolate reductase deficiency"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E7219",
            "display": "Other disorders of sulfur-bearing amino-acid metabolism"
        }
    ],
    "E83110": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "E83110",
        "display": "Hereditary hemochromatosis"
    },
    "E87": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E870",
            "display": "Hyperosmolality and hypernatremia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E875",
            "display": "Hyperkalemia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E872",
            "display": "Acidosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8720",
            "display": "Acidosis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8721",
            "display": "Acute metabolic acidosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8722",
            "display": "Chronic metabolic acidosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8729",
            "display": "Other acidosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E873",
            "display": "Alkalosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E874",
            "display": "Mixed disorder of acid-base balance"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E876",
            "display": "Hypokalemia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8770",
            "display": "Fluid overload, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8771",
            "display": "Transfusion associated circulatory overload"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E8779",
            "display": "Other fluid overload"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E878",
            "display": "Other disorders of electrolyte and fluid balance, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "E871",
            "display": "Hypo-osmolality and hyponatremia"
        }
    ],
    "F17298": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "F17298",
        "display": "Nicotine dependence, other tobacco product, with other nicotine-induced disorders"
    },
    "F41": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F418",
            "display": "Other specified anxiety disorders"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F410",
            "display": "Panic disorder [episodic paroxysmal anxiety]"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F411",
            "display": "Generalized anxiety disorder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F413",
            "display": "Other mixed anxiety disorders"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F419",
            "display": "Anxiety disorder, unspecified"
        }
    ],
    "F412": [],
    "F4180": [],
    "F42": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F428",
            "display": "Other obsessive-compulsive disorder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F429",
            "display": "Obsessive-compulsive disorder, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F423",
            "display": "Hoarding disorder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F422",
            "display": "Mixed obsessional thoughts and acts"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F424",
            "display": "Excoriation (skin-picking) disorder"
        }
    ],
    "F431": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F4311",
            "display": "Post-traumatic stress disorder, acute"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F4310",
            "display": "Post-traumatic stress disorder, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "F4312",
            "display": "Post-traumatic stress disorder, chronic"
        }
    ],
    "F4481": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "F4481",
        "display": "Dissociative identity disorder"
    },
    "F514": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "F514",
        "display": "Sleep terrors [night terrors]"
    },
    "F519": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "F519",
        "display": "Sleep disorder not due to a substance or known physiological condition, unspecified"
    },
    "F9880": [],
    "G249": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "G249",
        "display": "Dystonia, unspecified"
    },
    "G406": [],
    "G4340": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43401",
            "display": "Hemiplegic migraine, not intractable, with status migrainosus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43409",
            "display": "Hemiplegic migraine, not intractable, without status migrainosus"
        }
    ],
    "G439": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43919",
            "display": "Migraine, unspecified, intractable, without status migrainosus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43901",
            "display": "Migraine, unspecified, not intractable, with status migrainosus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43909",
            "display": "Migraine, unspecified, not intractable, without status migrainosus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G43911",
            "display": "Migraine, unspecified, intractable, with status migrainosus"
        }
    ],
    "G44221": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "G44221",
        "display": "Chronic tension-type headache, intractable"
    },
    "G459": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "G459",
        "display": "Transient cerebral ischemic attack, unspecified"
    },
    "G471": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4710",
            "display": "Hypersomnia, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4714",
            "display": "Hypersomnia due to medical condition"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4711",
            "display": "Idiopathic hypersomnia with long sleep time"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4712",
            "display": "Idiopathic hypersomnia without long sleep time"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4713",
            "display": "Recurrent hypersomnia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G4719",
            "display": "Other hypersomnia"
        }
    ],
    "G560": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G5602",
            "display": "Carpal tunnel syndrome, left upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G5601",
            "display": "Carpal tunnel syndrome, right upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G5600",
            "display": "Carpal tunnel syndrome, unspecified upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G5603",
            "display": "Carpal tunnel syndrome, bilateral upper limbs"
        }
    ],
    "G5700": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "G5700",
        "display": "Lesion of sciatic nerve, unspecified lower limb"
    },
    "G90": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G909",
            "display": "Disorder of the autonomic nervous system, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9050",
            "display": "Complex regional pain syndrome I, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G908",
            "display": "Other disorders of autonomic nervous system"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9059",
            "display": "Complex regional pain syndrome I of other specified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G902",
            "display": "Horner's syndrome"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90513",
            "display": "Complex regional pain syndrome I of upper limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90512",
            "display": "Complex regional pain syndrome I of left upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90519",
            "display": "Complex regional pain syndrome I of unspecified upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90521",
            "display": "Complex regional pain syndrome I of right lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90522",
            "display": "Complex regional pain syndrome I of left lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90523",
            "display": "Complex regional pain syndrome I of lower limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90529",
            "display": "Complex regional pain syndrome I of unspecified lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9081",
            "display": "Serotonin syndrome"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9089",
            "display": "Other disorders of autonomic nervous system"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90A",
            "display": "Postural orthostatic tachycardia syndrome [POTS]"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9001",
            "display": "Carotid sinus syncope"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90B",
            "display": "LMNB1-related autosomal dominant leukodystrophy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9009",
            "display": "Other idiopathic peripheral autonomic neuropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G901",
            "display": "Familial dysautonomia [Riley-Day]"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G903",
            "display": "Multi-system degeneration of the autonomic nervous system"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G904",
            "display": "Autonomic dysreflexia"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90511",
            "display": "Complex regional pain syndrome I of right upper limb"
        }
    ],
    "G905": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9050",
            "display": "Complex regional pain syndrome I, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G9059",
            "display": "Complex regional pain syndrome I of other specified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90513",
            "display": "Complex regional pain syndrome I of upper limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90519",
            "display": "Complex regional pain syndrome I of unspecified upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90521",
            "display": "Complex regional pain syndrome I of right lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90522",
            "display": "Complex regional pain syndrome I of left lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90523",
            "display": "Complex regional pain syndrome I of lower limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90529",
            "display": "Complex regional pain syndrome I of unspecified lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90512",
            "display": "Complex regional pain syndrome I of left upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "G90511",
            "display": "Complex regional pain syndrome I of right upper limb"
        }
    ],
    "H0412": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H04121",
            "display": "Dry eye syndrome of right lacrimal gland"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H04122",
            "display": "Dry eye syndrome of left lacrimal gland"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H04129",
            "display": "Dry eye syndrome of unspecified lacrimal gland"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H04123",
            "display": "Dry eye syndrome of bilateral lacrimal glands"
        }
    ],
    "H151": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15119",
            "display": "Episcleritis periodica fugax, unspecified eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15109",
            "display": "Unspecified episcleritis, unspecified eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15129",
            "display": "Nodular episcleritis, unspecified eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15111",
            "display": "Episcleritis periodica fugax, right eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15112",
            "display": "Episcleritis periodica fugax, left eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15101",
            "display": "Unspecified episcleritis, right eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15121",
            "display": "Nodular episcleritis, right eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15122",
            "display": "Nodular episcleritis, left eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15123",
            "display": "Nodular episcleritis, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15113",
            "display": "Episcleritis periodica fugax, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15102",
            "display": "Unspecified episcleritis, left eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H15103",
            "display": "Unspecified episcleritis, bilateral"
        }
    ],
    "H3531": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353110",
            "display": "Nonexudative age-related macular degeneration, right eye, stage unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353130",
            "display": "Nonexudative age-related macular degeneration, bilateral, stage unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353190",
            "display": "Nonexudative age-related macular degeneration, unspecified eye, stage unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353113",
            "display": "Nonexudative age-related macular degeneration, right eye, advanced atrophic without subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353114",
            "display": "Nonexudative age-related macular degeneration, right eye, advanced atrophic with subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353120",
            "display": "Nonexudative age-related macular degeneration, left eye, stage unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353121",
            "display": "Nonexudative age-related macular degeneration, left eye, early dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353122",
            "display": "Nonexudative age-related macular degeneration, left eye, intermediate dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353123",
            "display": "Nonexudative age-related macular degeneration, left eye, advanced atrophic without subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353124",
            "display": "Nonexudative age-related macular degeneration, left eye, advanced atrophic with subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353194",
            "display": "Nonexudative age-related macular degeneration, unspecified eye, advanced atrophic with subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353131",
            "display": "Nonexudative age-related macular degeneration, bilateral, early dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353132",
            "display": "Nonexudative age-related macular degeneration, bilateral, intermediate dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353133",
            "display": "Nonexudative age-related macular degeneration, bilateral, advanced atrophic without subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353134",
            "display": "Nonexudative age-related macular degeneration, bilateral, advanced atrophic with subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353191",
            "display": "Nonexudative age-related macular degeneration, unspecified eye, early dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353192",
            "display": "Nonexudative age-related macular degeneration, unspecified eye, intermediate dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353193",
            "display": "Nonexudative age-related macular degeneration, unspecified eye, advanced atrophic without subfoveal involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353112",
            "display": "Nonexudative age-related macular degeneration, right eye, intermediate dry stage"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H353111",
            "display": "Nonexudative age-related macular degeneration, right eye, early dry stage"
        }
    ],
    "H4381": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H43811",
            "display": "Vitreous degeneration, right eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H43812",
            "display": "Vitreous degeneration, left eye"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H43813",
            "display": "Vitreous degeneration, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H43819",
            "display": "Vitreous degeneration, unspecified eye"
        }
    ],
    "H4711": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "H4711",
        "display": "Papilledema associated with increased intracranial pressure"
    },
    "H8110": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "H8110",
        "display": "Benign paroxysmal vertigo, unspecified ear"
    },
    "H815": [],
    "H8309": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "H8309",
        "display": "Labyrinthitis, unspecified ear"
    },
    "H931": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H9311",
            "display": "Tinnitus, right ear"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H9312",
            "display": "Tinnitus, left ear"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H9319",
            "display": "Tinnitus, unspecified ear"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "H9313",
            "display": "Tinnitus, bilateral"
        }
    ],
    "I652": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I6521",
            "display": "Occlusion and stenosis of right carotid artery"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I6522",
            "display": "Occlusion and stenosis of left carotid artery"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I6523",
            "display": "Occlusion and stenosis of bilateral carotid arteries"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I6529",
            "display": "Occlusion and stenosis of unspecified carotid artery"
        }
    ],
    "I730": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I7300",
            "display": "Raynaud's syndrome without gangrene"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "I7301",
            "display": "Raynaud's syndrome with gangrene"
        }
    ],
    "I776": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "I776",
        "display": "Arteritis, unspecified"
    },
    "I878": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "I878",
        "display": "Other specified disorders of veins"
    },
    "J30": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J302",
            "display": "Other seasonal allergic rhinitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J3089",
            "display": "Other allergic rhinitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J3081",
            "display": "Allergic rhinitis due to animal (cat) (dog) hair and dander"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J309",
            "display": "Allergic rhinitis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J305",
            "display": "Allergic rhinitis due to food"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J301",
            "display": "Allergic rhinitis due to pollen"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J300",
            "display": "Vasomotor rhinitis"
        }
    ],
    "J308": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J3089",
            "display": "Other allergic rhinitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J3081",
            "display": "Allergic rhinitis due to animal (cat) (dog) hair and dander"
        }
    ],
    "J3089": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "J3089",
        "display": "Other allergic rhinitis"
    },
    "J310": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "J310",
        "display": "Chronic rhinitis"
    },
    "J33": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J331",
            "display": "Polypoid sinus degeneration"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J339",
            "display": "Nasal polyp, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J330",
            "display": "Polyp of nasal cavity"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J338",
            "display": "Other polyp of sinus"
        }
    ],
    "J370": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "J370",
        "display": "Chronic laryngitis"
    },
    "J45": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4541",
            "display": "Moderate persistent asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4521",
            "display": "Mild intermittent asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4551",
            "display": "Severe persistent asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4531",
            "display": "Mild persistent asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4540",
            "display": "Moderate persistent asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4542",
            "display": "Moderate persistent asthma with status asthmaticus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4550",
            "display": "Severe persistent asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4552",
            "display": "Severe persistent asthma with status asthmaticus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45901",
            "display": "Unspecified asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45902",
            "display": "Unspecified asthma with status asthmaticus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45909",
            "display": "Unspecified asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45990",
            "display": "Exercise induced bronchospasm"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45991",
            "display": "Cough variant asthma"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4520",
            "display": "Mild intermittent asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45998",
            "display": "Other asthma"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4522",
            "display": "Mild intermittent asthma with status asthmaticus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4530",
            "display": "Mild persistent asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J4532",
            "display": "Mild persistent asthma with status asthmaticus"
        }
    ],
    "J459": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45901",
            "display": "Unspecified asthma with (acute) exacerbation"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45902",
            "display": "Unspecified asthma with status asthmaticus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45909",
            "display": "Unspecified asthma, uncomplicated"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45990",
            "display": "Exercise induced bronchospasm"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45991",
            "display": "Cough variant asthma"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "J45998",
            "display": "Other asthma"
        }
    ],
    "K01": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K010",
            "display": "Embedded teeth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K011",
            "display": "Impacted teeth"
        }
    ],
    "K076": [],
    "K20": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K200",
            "display": "Eosinophilic esophagitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K208",
            "display": "Other esophagitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2080",
            "display": "Other esophagitis without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2081",
            "display": "Other esophagitis with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K209",
            "display": "Esophagitis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2090",
            "display": "Esophagitis, unspecified without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2091",
            "display": "Esophagitis, unspecified with bleeding"
        }
    ],
    "K21": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K219",
            "display": "Gastro-esophageal reflux disease without esophagitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K210",
            "display": "Gastro-esophageal reflux disease with esophagitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2100",
            "display": "Gastro-esophageal reflux disease with esophagitis, without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K2101",
            "display": "Gastro-esophageal reflux disease with esophagitis, with bleeding"
        }
    ],
    "K42": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K421",
            "display": "Umbilical hernia with gangrene"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K420",
            "display": "Umbilical hernia with obstruction, without gangrene"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K429",
            "display": "Umbilical hernia without obstruction or gangrene"
        }
    ],
    "K57": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5792",
            "display": "Diverticulitis of intestine, part unspecified, without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5720",
            "display": "Diverticulitis of large intestine with perforation and abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5732",
            "display": "Diverticulitis of large intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5712",
            "display": "Diverticulitis of small intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5710",
            "display": "Diverticulosis of small intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5791",
            "display": "Diverticulosis of intestine, part unspecified, without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5700",
            "display": "Diverticulitis of small intestine with perforation and abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5711",
            "display": "Diverticulosis of small intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5740",
            "display": "Diverticulitis of both small and large intestine with perforation and abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5713",
            "display": "Diverticulitis of small intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5730",
            "display": "Diverticulosis of large intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5733",
            "display": "Diverticulitis of large intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5731",
            "display": "Diverticulosis of large intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5741",
            "display": "Diverticulitis of both small and large intestine with perforation and abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5750",
            "display": "Diverticulosis of both small and large intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5751",
            "display": "Diverticulosis of both small and large intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5752",
            "display": "Diverticulitis of both small and large intestine without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5753",
            "display": "Diverticulitis of both small and large intestine without perforation or abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5780",
            "display": "Diverticulitis of intestine, part unspecified, with perforation and abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5781",
            "display": "Diverticulitis of intestine, part unspecified, with perforation and abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5790",
            "display": "Diverticulosis of intestine, part unspecified, without perforation or abscess without bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5721",
            "display": "Diverticulitis of large intestine with perforation and abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5701",
            "display": "Diverticulitis of small intestine with perforation and abscess with bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K5793",
            "display": "Diverticulitis of intestine, part unspecified, without perforation or abscess with bleeding"
        }
    ],
    "K582": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "K582",
        "display": "Mixed irritable bowel syndrome"
    },
    "K5989": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "K5989",
        "display": "Other specified functional intestinal disorders"
    },
    "K599": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "K599",
        "display": "Functional intestinal disorder, unspecified"
    },
    "K63821": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K638211",
            "display": "Small intestinal bacterial overgrowth, hydrogen-subtype"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K638212",
            "display": "Small intestinal bacterial overgrowth, hydrogen sulfide-subtype"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "K638219",
            "display": "Small intestinal bacterial overgrowth, unspecified"
        }
    ],
    "K828": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "K828",
        "display": "Other specified diseases of gallbladder"
    },
    "K869": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "K869",
        "display": "Disease of pancreas, unspecified"
    },
    "L089": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "L089",
        "display": "Local infection of the skin and subcutaneous tissue, unspecified"
    },
    "L405": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4059",
            "display": "Other psoriatic arthropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4051",
            "display": "Distal interphalangeal psoriatic arthropathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4052",
            "display": "Psoriatic arthritis mutilans"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4050",
            "display": "Arthropathic psoriasis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4053",
            "display": "Psoriatic spondylitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "L4054",
            "display": "Psoriatic juvenile arthropathy"
        }
    ],
    "L502": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "L502",
        "display": "Urticaria due to cold and heat"
    },
    "M064": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M064",
        "display": "Inflammatory polyarthropathy"
    },
    "M19041": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M19041",
        "display": "Primary osteoarthritis, right hand"
    },
    "M214": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2140",
            "display": "Flat foot [pes planus] (acquired), unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2141",
            "display": "Flat foot [pes planus] (acquired), right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2142",
            "display": "Flat foot [pes planus] (acquired), left foot"
        }
    ],
    "M24": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2420",
            "display": "Disorder of ligament, unspecified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2450",
            "display": "Contracture, unspecified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2410",
            "display": "Other articular cartilage disorders, unspecified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24273",
            "display": "Disorder of ligament, unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2440",
            "display": "Recurrent dislocation, unspecified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24573",
            "display": "Contracture, unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2460",
            "display": "Ankylosis, unspecified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24576",
            "display": "Contracture, unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24659",
            "display": "Ankylosis, unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24669",
            "display": "Ankylosis, unspecified knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24551",
            "display": "Contracture, right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24512",
            "display": "Contracture, left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24511",
            "display": "Contracture, right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24519",
            "display": "Contracture, unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24569",
            "display": "Contracture, unspecified knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24159",
            "display": "Other articular cartilage disorders, unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24673",
            "display": "Ankylosis, unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24149",
            "display": "Other articular cartilage disorders, unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24073",
            "display": "Loose body in unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2408",
            "display": "Loose body, other site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24072",
            "display": "Loose body in left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24071",
            "display": "Loose body in right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24572",
            "display": "Contracture, left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24476",
            "display": "Recurrent dislocation, unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24571",
            "display": "Contracture, right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24676",
            "display": "Ankylosis, unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24542",
            "display": "Contracture, left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24119",
            "display": "Other articular cartilage disorders, unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24541",
            "display": "Contracture, right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24469",
            "display": "Recurrent dislocation, unspecified knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24549",
            "display": "Contracture, unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24051",
            "display": "Loose body in right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24129",
            "display": "Other articular cartilage disorders, unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24852",
            "display": "Other specific joint derangements of left hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2430",
            "display": "Pathological dislocation of unspecified joint, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24039",
            "display": "Loose body in unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24059",
            "display": "Loose body in unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24052",
            "display": "Loose body in left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24839",
            "display": "Other specific joint derangements of unspecified wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24352",
            "display": "Pathological dislocation of left hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24459",
            "display": "Recurrent dislocation, unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24359",
            "display": "Pathological dislocation of unspecified hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24029",
            "display": "Loose body in unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24021",
            "display": "Loose body in right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24876",
            "display": "Other specific joint derangements of unspecified foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24429",
            "display": "Recurrent dislocation, unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24473",
            "display": "Recurrent dislocation, unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M247",
            "display": "Protrusio acetabuli"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24239",
            "display": "Disorder of ligament, unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24249",
            "display": "Disorder of ligament, unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24439",
            "display": "Recurrent dislocation, unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24369",
            "display": "Pathological dislocation of unspecified knee, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24443",
            "display": "Recurrent dislocation, unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24452",
            "display": "Recurrent dislocation, left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24151",
            "display": "Other articular cartilage disorders, right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24172",
            "display": "Other articular cartilage disorders, left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24241",
            "display": "Disorder of ligament, right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24362",
            "display": "Pathological dislocation of left knee, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24622",
            "display": "Ankylosis, left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24111",
            "display": "Other articular cartilage disorders, right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24122",
            "display": "Other articular cartilage disorders, left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24231",
            "display": "Disorder of ligament, right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24221",
            "display": "Disorder of ligament, right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24474",
            "display": "Recurrent dislocation, right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24432",
            "display": "Recurrent dislocation, left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24372",
            "display": "Pathological dislocation of left ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24822",
            "display": "Other specific joint derangements of left elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24075",
            "display": "Loose body in left toe joint(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24475",
            "display": "Recurrent dislocation, left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24242",
            "display": "Disorder of ligament, left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24631",
            "display": "Ankylosis, right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24675",
            "display": "Ankylosis, left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24652",
            "display": "Ankylosis, left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24341",
            "display": "Pathological dislocation of right hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24832",
            "display": "Other specific joint derangements of left wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24321",
            "display": "Pathological dislocation of right elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24142",
            "display": "Other articular cartilage disorders, left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24121",
            "display": "Other articular cartilage disorders, right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24174",
            "display": "Other articular cartilage disorders, right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24462",
            "display": "Recurrent dislocation, left knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24479",
            "display": "Recurrent dislocation, unspecified toe(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24311",
            "display": "Pathological dislocation of right shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24312",
            "display": "Pathological dislocation of left shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24141",
            "display": "Other articular cartilage disorders, right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24322",
            "display": "Pathological dislocation of left elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24672",
            "display": "Ankylosis, left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24049",
            "display": "Loose body in unspecified finger joint(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24461",
            "display": "Recurrent dislocation, right knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24441",
            "display": "Recurrent dislocation, right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24421",
            "display": "Recurrent dislocation, right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24331",
            "display": "Pathological dislocation of right wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24811",
            "display": "Other specific joint derangements of right shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24574",
            "display": "Contracture, right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24276",
            "display": "Disorder of ligament, unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24575",
            "display": "Contracture, left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24531",
            "display": "Contracture, right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24619",
            "display": "Ankylosis, unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24532",
            "display": "Contracture, left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24011",
            "display": "Loose body in right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24412",
            "display": "Recurrent dislocation, left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24812",
            "display": "Other specific joint derangements of left shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24629",
            "display": "Ankylosis, unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24173",
            "display": "Other articular cartilage disorders, unspecified ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24176",
            "display": "Other articular cartilage disorders, unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24019",
            "display": "Loose body in unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24339",
            "display": "Pathological dislocation of unspecified wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24031",
            "display": "Loose body in right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24829",
            "display": "Other specific joint derangements of unspecified elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24131",
            "display": "Other articular cartilage disorders, right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24132",
            "display": "Other articular cartilage disorders, left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24562",
            "display": "Contracture, left knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24139",
            "display": "Other articular cartilage disorders, unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24319",
            "display": "Pathological dislocation of unspecified shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24219",
            "display": "Disorder of ligament, unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2428",
            "display": "Disorder of ligament, vertebrae"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24012",
            "display": "Loose body in left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24373",
            "display": "Pathological dislocation of unspecified ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24229",
            "display": "Disorder of ligament, unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24559",
            "display": "Contracture, unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24819",
            "display": "Other specific joint derangements of unspecified shoulder, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24639",
            "display": "Ankylosis, unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24411",
            "display": "Recurrent dislocation, right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24851",
            "display": "Other specific joint derangements of right hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2400",
            "display": "Loose body in unspecified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24376",
            "display": "Pathological dislocation of unspecified foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24859",
            "display": "Other specific joint derangements of unspecified hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24522",
            "display": "Contracture, left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24521",
            "display": "Contracture, right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24662",
            "display": "Ankylosis, left knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24329",
            "display": "Pathological dislocation of unspecified elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24349",
            "display": "Pathological dislocation of unspecified hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24649",
            "display": "Ankylosis, unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24873",
            "display": "Other specific joint derangements of unspecified ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24661",
            "display": "Ankylosis, right knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24561",
            "display": "Contracture, right knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24032",
            "display": "Loose body in left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24529",
            "display": "Contracture, unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24552",
            "display": "Contracture, left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24022",
            "display": "Loose body in left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2480",
            "display": "Other specific joint derangements of unspecified joint, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24419",
            "display": "Recurrent dislocation, unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24446",
            "display": "Recurrent dislocation, unspecified finger"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24539",
            "display": "Contracture, unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24849",
            "display": "Other specific joint derangements of unspecified hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M249",
            "display": "Joint derangement, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2419",
            "display": "Other articular cartilage disorders, other specified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2429",
            "display": "Disorder of ligament, other specified site"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2439",
            "display": "Pathological dislocation of other specified joint, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2449",
            "display": "Recurrent dislocation, other specified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2459",
            "display": "Contracture, other specified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2469",
            "display": "Ankylosis, other specified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24175",
            "display": "Other articular cartilage disorders, left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2489",
            "display": "Other specific joint derangement of other specified joint, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24651",
            "display": "Ankylosis, right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24232",
            "display": "Disorder of ligament, left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24422",
            "display": "Recurrent dislocation, left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24259",
            "display": "Disorder of ligament, unspecified hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24611",
            "display": "Ankylosis, right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24642",
            "display": "Ankylosis, left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24674",
            "display": "Ankylosis, right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24841",
            "display": "Other specific joint derangements of right hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24112",
            "display": "Other articular cartilage disorders, left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24641",
            "display": "Ankylosis, right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24444",
            "display": "Recurrent dislocation, right finger"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24361",
            "display": "Pathological dislocation of right knee, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24621",
            "display": "Ankylosis, right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24442",
            "display": "Recurrent dislocation, left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24872",
            "display": "Other specific joint derangements of left ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24332",
            "display": "Pathological dislocation of left wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24445",
            "display": "Recurrent dislocation, left finger"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24671",
            "display": "Ankylosis, right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24875",
            "display": "Other specific joint derangements left foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24351",
            "display": "Pathological dislocation of right hip, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24821",
            "display": "Other specific joint derangements of right elbow, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24371",
            "display": "Pathological dislocation of right ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24374",
            "display": "Pathological dislocation of right foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24222",
            "display": "Disorder of ligament, left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24477",
            "display": "Recurrent dislocation, right toe(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24471",
            "display": "Recurrent dislocation, right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24874",
            "display": "Other specific joint derangements of right foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24451",
            "display": "Recurrent dislocation, right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24472",
            "display": "Recurrent dislocation, left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24431",
            "display": "Recurrent dislocation, right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24252",
            "display": "Disorder of ligament, left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24152",
            "display": "Other articular cartilage disorders, left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24212",
            "display": "Disorder of ligament, left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24275",
            "display": "Disorder of ligament, left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24271",
            "display": "Disorder of ligament, right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24171",
            "display": "Other articular cartilage disorders, right ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24342",
            "display": "Pathological dislocation of left hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24041",
            "display": "Loose body in right finger joint(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24251",
            "display": "Disorder of ligament, right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24612",
            "display": "Ankylosis, left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24211",
            "display": "Disorder of ligament, right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24076",
            "display": "Loose body in unspecified toe joints"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24632",
            "display": "Ankylosis, left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24375",
            "display": "Pathological dislocation of left foot, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24042",
            "display": "Loose body in left finger joint(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24831",
            "display": "Other specific joint derangements of right wrist, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24074",
            "display": "Loose body in right toe joint(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24871",
            "display": "Other specific joint derangements of right ankle, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24842",
            "display": "Other specific joint derangements of left hand, not elsewhere classified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24272",
            "display": "Disorder of ligament, left ankle"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24478",
            "display": "Recurrent dislocation, left toe(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M24274",
            "display": "Disorder of ligament, right foot"
        }
    ],
    "M24151": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M24151",
        "display": "Other articular cartilage disorders, right hip"
    },
    "M255": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2550",
            "display": "Pain in unspecified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25579",
            "display": "Pain in unspecified ankle and joints of unspecified foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25542",
            "display": "Pain in joints of left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25541",
            "display": "Pain in joints of right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25512",
            "display": "Pain in left shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25569",
            "display": "Pain in unspecified knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25511",
            "display": "Pain in right shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25529",
            "display": "Pain in unspecified elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25522",
            "display": "Pain in left elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25521",
            "display": "Pain in right elbow"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25562",
            "display": "Pain in left knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25561",
            "display": "Pain in right knee"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25572",
            "display": "Pain in left ankle and joints of left foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25519",
            "display": "Pain in unspecified shoulder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25531",
            "display": "Pain in right wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25532",
            "display": "Pain in left wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25539",
            "display": "Pain in unspecified wrist"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25571",
            "display": "Pain in right ankle and joints of right foot"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25552",
            "display": "Pain in left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M2559",
            "display": "Pain in other specified joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25551",
            "display": "Pain in right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25549",
            "display": "Pain in joints of unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25559",
            "display": "Pain in unspecified hip"
        }
    ],
    "M2555": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25551",
            "display": "Pain in right hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25552",
            "display": "Pain in left hip"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M25559",
            "display": "Pain in unspecified hip"
        }
    ],
    "M2660": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26609",
            "display": "Unspecified temporomandibular joint disorder, unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26601",
            "display": "Right temporomandibular joint disorder, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26603",
            "display": "Bilateral temporomandibular joint disorder, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26602",
            "display": "Left temporomandibular joint disorder, unspecified"
        }
    ],
    "M2662": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26621",
            "display": "Arthralgia of right temporomandibular  joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26621",
            "display": "Arthralgia of right temporomandibular joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26622",
            "display": "Arthralgia of left temporomandibular joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26623",
            "display": "Arthralgia of bilateral temporomandibular joint"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M26629",
            "display": "Arthralgia of temporomandibular joint, unspecified side"
        }
    ],
    "M26629": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M26629",
        "display": "Arthralgia of temporomandibular joint, unspecified side"
    },
    "M3320": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M3320",
        "display": "Polymyositis, organ involvement unspecified"
    },
    "M339": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M3390",
            "display": "Dermatopolymyositis, unspecified, organ involvement unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M3392",
            "display": "Dermatopolymyositis, unspecified with myopathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M3391",
            "display": "Dermatopolymyositis, unspecified with respiratory involvement"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M3393",
            "display": "Dermatopolymyositis, unspecified without myopathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M3399",
            "display": "Dermatopolymyositis, unspecified with other organ involvement"
        }
    ],
    "M41": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41119",
            "display": "Juvenile idiopathic scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4100",
            "display": "Infantile idiopathic scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4120",
            "display": "Other idiopathic scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M419",
            "display": "Scoliosis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4134",
            "display": "Thoracogenic scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4126",
            "display": "Other idiopathic scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4124",
            "display": "Other idiopathic scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4186",
            "display": "Other forms of scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4182",
            "display": "Other forms of scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4184",
            "display": "Other forms of scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4146",
            "display": "Neuromuscular scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41115",
            "display": "Juvenile idiopathic scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41116",
            "display": "Juvenile idiopathic scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41117",
            "display": "Juvenile idiopathic scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41122",
            "display": "Adolescent idiopathic scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41123",
            "display": "Adolescent idiopathic scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41124",
            "display": "Adolescent idiopathic scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41125",
            "display": "Adolescent idiopathic scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41126",
            "display": "Adolescent idiopathic scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41127",
            "display": "Adolescent idiopathic scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41129",
            "display": "Adolescent idiopathic scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4122",
            "display": "Other idiopathic scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4123",
            "display": "Other idiopathic scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4125",
            "display": "Other idiopathic scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4127",
            "display": "Other idiopathic scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4130",
            "display": "Thoracogenic scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4135",
            "display": "Thoracogenic scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4140",
            "display": "Neuromuscular scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4142",
            "display": "Neuromuscular scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4143",
            "display": "Neuromuscular scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4144",
            "display": "Neuromuscular scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4145",
            "display": "Neuromuscular scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4147",
            "display": "Neuromuscular scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4150",
            "display": "Other secondary scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4152",
            "display": "Other secondary scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4153",
            "display": "Other secondary scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4154",
            "display": "Other secondary scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4155",
            "display": "Other secondary scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4156",
            "display": "Other secondary scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4157",
            "display": "Other secondary scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4180",
            "display": "Other forms of scoliosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4183",
            "display": "Other forms of scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4185",
            "display": "Other forms of scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4187",
            "display": "Other forms of scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4141",
            "display": "Neuromuscular scoliosis, occipito-atlanto-axial region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4102",
            "display": "Infantile idiopathic scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4103",
            "display": "Infantile idiopathic scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4104",
            "display": "Infantile idiopathic scoliosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4105",
            "display": "Infantile idiopathic scoliosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4106",
            "display": "Infantile idiopathic scoliosis, lumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4107",
            "display": "Infantile idiopathic scoliosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4108",
            "display": "Infantile idiopathic scoliosis, sacral and sacrococcygeal region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41112",
            "display": "Juvenile idiopathic scoliosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41113",
            "display": "Juvenile idiopathic scoliosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M41114",
            "display": "Juvenile idiopathic scoliosis, thoracic region"
        }
    ],
    "M4796": [],
    "M480": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M48062",
            "display": "Spinal stenosis, lumbar region with neurogenic claudication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4801",
            "display": "Spinal stenosis, occipito-atlanto-axial region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4802",
            "display": "Spinal stenosis, cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4803",
            "display": "Spinal stenosis, cervicothoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4804",
            "display": "Spinal stenosis, thoracic region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4805",
            "display": "Spinal stenosis, thoracolumbar region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M48061",
            "display": "Spinal stenosis, lumbar region without neurogenic claudication"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4807",
            "display": "Spinal stenosis, lumbosacral region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4800",
            "display": "Spinal stenosis, site unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M4808",
            "display": "Spinal stenosis, sacral and sacrococcygeal region"
        }
    ],
    "M4802": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M4802",
        "display": "Spinal stenosis, cervical region"
    },
    "M501": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M5010",
            "display": "Cervical disc disorder with radiculopathy, unspecified cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M5011",
            "display": "Cervical disc disorder with radiculopathy,  high cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M5011",
            "display": "Cervical disc disorder with radiculopathy, high cervical region"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50120",
            "display": "Mid-cervical disc disorder, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50120",
            "display": "Mid-cervical disc disorder, unspecified level"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50121",
            "display": "Cervical disc disorder at C4-C5 level with radiculopathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50122",
            "display": "Cervical disc disorder at C5-C6 level with radiculopathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50123",
            "display": "Cervical disc disorder at C6-C7 level with radiculopathy"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M5013",
            "display": "Cervical disc disorder with radiculopathy, cervicothoracic region"
        }
    ],
    "M5022": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50220",
            "display": "Other cervical disc displacement, mid-cervical region, unspecified level"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50221",
            "display": "Other cervical disc displacement at C4-C5 level"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50222",
            "display": "Other cervical disc displacement at C5-C6 level"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M50223",
            "display": "Other cervical disc displacement at C6-C7 level"
        }
    ],
    "M539": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M539",
        "display": "Dorsopathy, unspecified"
    },
    "M763": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M7630",
            "display": "Iliotibial band syndrome, unspecified leg"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M7631",
            "display": "Iliotibial band syndrome, right leg"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M7632",
            "display": "Iliotibial band syndrome, left leg"
        }
    ],
    "M791": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M791",
        "display": "Myalgia"
    },
    "M79606": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M79606",
        "display": "Pain in leg, unspecified"
    },
    "M7964": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79643",
            "display": "Pain in unspecified hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79646",
            "display": "Pain in unspecified finger(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79641",
            "display": "Pain in right hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79642",
            "display": "Pain in left hand"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79644",
            "display": "Pain in right finger(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "M79645",
            "display": "Pain in left finger(s)"
        }
    ],
    "M940": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M940",
        "display": "Chondrocostal junction syndrome [Tietze]"
    },
    "M9905": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "M9905",
        "display": "Segmental and somatic dysfunction of pelvic region"
    },
    "N600": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N6001",
            "display": "Solitary cyst of right breast"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N6002",
            "display": "Solitary cyst of left breast"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N6009",
            "display": "Solitary cyst of unspecified breast"
        }
    ],
    "N80": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N809",
            "display": "Endometriosis, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803",
            "display": "Endometriosis of pelvic peritoneum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N805",
            "display": "Endometriosis of intestine"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N806",
            "display": "Endometriosis in cutaneous scar"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N808",
            "display": "Other endometriosis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N801",
            "display": "Endometriosis of ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80101",
            "display": "Endometriosis of right ovary, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80102",
            "display": "Endometriosis of left ovary, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80103",
            "display": "Endometriosis of bilateral ovaries, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80109",
            "display": "Endometriosis of ovary, unspecified side, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80111",
            "display": "Superficial endometriosis of right ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80112",
            "display": "Superficial endometriosis of left ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80113",
            "display": "Superficial endometriosis of bilateral ovaries"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80119",
            "display": "Superficial endometriosis of ovary, unspecified ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80121",
            "display": "Deep endometriosis of right ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80122",
            "display": "Deep endometriosis of left ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80123",
            "display": "Deep endometriosis of bilateral ovaries"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80129",
            "display": "Deep endometriosis of ovary, unspecified ovary"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N802",
            "display": "Endometriosis of fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80201",
            "display": "Endometriosis of right fallopian tube, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80202",
            "display": "Endometriosis of left fallopian tube, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80203",
            "display": "Endometriosis of bilateral fallopian tubes, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80209",
            "display": "Endometriosis of unspecified fallopian tube, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80211",
            "display": "Superficial endometriosis of right fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80212",
            "display": "Superficial endometriosis of left fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80213",
            "display": "Superficial endometriosis of bilateral fallopian tubes"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80219",
            "display": "Superficial endometriosis of unspecified fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80221",
            "display": "Deep endometriosis of right fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80222",
            "display": "Deep endometriosis of left fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80223",
            "display": "Deep endometriosis of bilateral fallopian tubes"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80229",
            "display": "Deep endometriosis of unspecified fallopian tube"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8030",
            "display": "Endometriosis of pelvic peritoneum, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80311",
            "display": "Superficial endometriosis of the anterior cul-de-sac"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80312",
            "display": "Deep endometriosis of the anterior cul-de-sac"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80319",
            "display": "Endometriosis of the anterior cul-de-sac, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80321",
            "display": "Superficial endometriosis of the posterior cul-de-sac"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80322",
            "display": "Deep endometriosis of the posterior cul-de-sac"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80329",
            "display": "Endometriosis of the posterior cul-de-sac, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80331",
            "display": "Superficial endometriosis of the right pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80332",
            "display": "Superficial endometriosis of the left pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80333",
            "display": "Superficial endometriosis of bilateral pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80339",
            "display": "Superficial endometriosis of pelvic sidewall, unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80341",
            "display": "Deep endometriosis of the right pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80342",
            "display": "Deep endometriosis of the left pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80343",
            "display": "Deep endometriosis of the bilateral pelvic sidewall"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80349",
            "display": "Deep endometriosis of the pelvic sidewall, unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80351",
            "display": "Endometriosis of the right pelvic sidewall, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80352",
            "display": "Endometriosis of the left pelvic sidewall, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80353",
            "display": "Endometriosis of bilateral pelvic sidewall, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80359",
            "display": "Endometriosis of pelvic sidewall, unspecified side, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80361",
            "display": "Superficial endometriosis of the right pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80362",
            "display": "Superficial endometriosis of the left pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80363",
            "display": "Superficial endometriosis of bilateral pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80369",
            "display": "Superficial endometriosis of the pelvic brim, unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80371",
            "display": "Deep endometriosis of the right pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80372",
            "display": "Deep endometriosis of the left pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80373",
            "display": "Deep endometriosis of bilateral pelvic brim"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80379",
            "display": "Deep endometriosis of the pelvic brim, unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80381",
            "display": "Endometriosis of the right pelvic brim, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80382",
            "display": "Endometriosis of the left pelvic brim, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80383",
            "display": "Endometriosis of bilateral pelvic brim, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80389",
            "display": "Endometriosis of the pelvic brim, unspecified side, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80391",
            "display": "Superficial endometriosis of the pelvic peritoneum, other specified sites"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80392",
            "display": "Deep endometriosis of the pelvic peritoneum, other specified sites"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80399",
            "display": "Endometriosis of the pelvic peritoneum, other specified sites, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803A1",
            "display": "Superficial endometriosis of the right uterosacral ligament"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803A2",
            "display": "Superficial endometriosis of the left uterosacral ligament"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803A3",
            "display": "Superficial endometriosis of the bilateral uterosacral ligament(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803A9",
            "display": "Superficial endometriosis of the uterosacral ligament(s), unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803B1",
            "display": "Deep endometriosis of the right uterosacral ligament"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803B2",
            "display": "Deep endometriosis of the left uterosacral ligament"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803B3",
            "display": "Deep endometriosis of bilateral uterosacral ligament(s)"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803B9",
            "display": "Deep endometriosis of the uterosacral ligament(s), unspecified side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803C1",
            "display": "Endometriosis of the right uterosacral ligament, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803C2",
            "display": "Endometriosis of the left uterosacral ligament, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803C3",
            "display": "Endometriosis of bilateral uterosacral ligament(s), unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N803C9",
            "display": "Endometriosis of the uterosacral ligament(s), unspecified side, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N804",
            "display": "Endometriosis of rectovaginal septum and vagina"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8040",
            "display": "Endometriosis of rectovaginal septum, unspecified involvement of vagina"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8041",
            "display": "Endometriosis of rectovaginal septum without involvement of vagina"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8042",
            "display": "Endometriosis of rectovaginal septum with involvement of vagina"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8050",
            "display": "Endometriosis of intestine, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80511",
            "display": "Superficial endometriosis of the rectum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80512",
            "display": "Deep endometriosis of the rectum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80519",
            "display": "Endometriosis of the rectum, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80521",
            "display": "Superficial endometriosis of the sigmoid colon"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80522",
            "display": "Deep endometriosis of the sigmoid colon"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80529",
            "display": "Endometriosis of the sigmoid colon, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80531",
            "display": "Superficial endometriosis of the cecum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80532",
            "display": "Deep endometriosis of the cecum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80539",
            "display": "Endometriosis of the cecum, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80541",
            "display": "Superficial endometriosis of the appendix"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80542",
            "display": "Deep endometriosis of the appendix"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80549",
            "display": "Endometriosis of the appendix, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80551",
            "display": "Superficial endometriosis of other parts of the colon"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80552",
            "display": "Deep endometriosis of other parts of the colon"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80559",
            "display": "Endometriosis of other parts of the colon, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80561",
            "display": "Superficial endometriosis of the small intestine"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80562",
            "display": "Deep endometriosis of the small intestine"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80569",
            "display": "Endometriosis of the small intestine, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A0",
            "display": "Endometriosis of bladder, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A1",
            "display": "Superficial endometriosis of bladder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A2",
            "display": "Deep endometriosis of bladder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A41",
            "display": "Superficial endometriosis of right ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A42",
            "display": "Superficial endometriosis of left ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A43",
            "display": "Superficial endometriosis of bilateral ureters"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A49",
            "display": "Superficial endometriosis of unspecified ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A51",
            "display": "Deep endometriosis of right ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A52",
            "display": "Deep endometriosis of left ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A53",
            "display": "Deep endometriosis of bilateral ureters"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A59",
            "display": "Deep endometriosis of unspecified ureter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A61",
            "display": "Endometriosis of right ureter, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A62",
            "display": "Endometriosis of left ureter, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A63",
            "display": "Endometriosis of bilateral ureters, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80A69",
            "display": "Endometriosis of unspecified ureter, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B1",
            "display": "Endometriosis of pleura"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B2",
            "display": "Endometriosis of lung"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B31",
            "display": "Superficial endometriosis of diaphragm"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B32",
            "display": "Deep endometriosis of diaphragm"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B39",
            "display": "Endometriosis of diaphragm, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B4",
            "display": "Endometriosis of the pericardial space"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B5",
            "display": "Endometriosis of the mediastinal space"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80B6",
            "display": "Endometriosis of cardiothoracic space"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C0",
            "display": "Endometriosis of the abdomen, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C10",
            "display": "Endometriosis of the anterior abdominal wall, subcutaneous tissue"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C11",
            "display": "Endometriosis of the anterior abdominal wall, fascia and muscular layers"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C19",
            "display": "Endometriosis of the anterior abdominal wall, unspecified depth"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C2",
            "display": "Endometriosis of the umbilicus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C3",
            "display": "Endometriosis of the inguinal canal"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C4",
            "display": "Endometriosis of extra-pelvic abdominal peritoneum"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80C9",
            "display": "Endometriosis of other site of abdomen"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D0",
            "display": "Endometriosis of the pelvic nerves, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D1",
            "display": "Endometriosis of the sacral splanchnic nerves"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D2",
            "display": "Endometriosis of the sacral nerve roots"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D3",
            "display": "Endometriosis of the obturator nerve"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D4",
            "display": "Endometriosis of the sciatic nerve"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D5",
            "display": "Endometriosis of the pudendal nerve"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D6",
            "display": "Endometriosis of the femoral nerve"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N800",
            "display": "Endometriosis of uterus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N80D9",
            "display": "Endometriosis of other pelvic nerve"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8000",
            "display": "Endometriosis of the uterus, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8001",
            "display": "Superficial endometriosis of the uterus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8002",
            "display": "Deep endometriosis of the uterus"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N8003",
            "display": "Adenomyosis of the uterus"
        }
    ],
    "N8189": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "N8189",
        "display": "Other female genital prolapse"
    },
    "N819": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "N819",
        "display": "Female genital prolapse, unspecified"
    },
    "N8320": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N83201",
            "display": "Unspecified ovarian cyst, right side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N83202",
            "display": "Unspecified ovarian cyst, left side"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N83209",
            "display": "Unspecified ovarian cyst, unspecified side"
        }
    ],
    "N8500": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "N8500",
        "display": "Endometrial hyperplasia, unspecified"
    },
    "N943": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "N943",
        "display": "Premenstrual tension syndrome"
    },
    "N946": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "N946",
        "display": "Dysmenorrhea, unspecified"
    },
    "N95": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N959",
            "display": "Unspecified menopausal and perimenopausal disorder"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N958",
            "display": "Other specified menopausal and perimenopausal disorders"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N952",
            "display": "Postmenopausal atrophic vaginitis"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N950",
            "display": "Postmenopausal bleeding"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "N951",
            "display": "Menopausal and female climacteric states"
        }
    ],
    "Q438": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q438",
        "display": "Other specified congenital malformations of intestine"
    },
    "Q619": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q619",
        "display": "Cystic kidney disease, unspecified"
    },
    "Q758": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q758",
        "display": "Other specified congenital malformations of skull and face bones"
    },
    "Q760": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q760",
        "display": "Spina bifida occulta"
    },
    "Q7961": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q7961",
        "display": "Classical Ehlers-Danlos syndrome"
    },
    "Q7969": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q7969",
        "display": "Other Ehlers-Danlos syndromes"
    },
    "Q8789": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Q8789",
        "display": "Other specified congenital malformation syndromes, not elsewhere classified"
    },
    "R0402": [],
    "R0602": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R0602",
        "display": "Shortness of breath"
    },
    "R22": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2230",
            "display": "Localized swelling, mass and lump, unspecified upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R222",
            "display": "Localized swelling, mass and lump, trunk"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2240",
            "display": "Localized swelling, mass and lump, unspecified lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R221",
            "display": "Localized swelling, mass and lump, neck"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R220",
            "display": "Localized swelling, mass and lump, head"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R229",
            "display": "Localized swelling, mass and lump, unspecified"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2233",
            "display": "Localized swelling, mass and lump, upper limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2232",
            "display": "Localized swelling, mass and lump, left upper limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2241",
            "display": "Localized swelling, mass and lump, right lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2242",
            "display": "Localized swelling, mass and lump, left lower limb"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2243",
            "display": "Localized swelling, mass and lump, lower limb, bilateral"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "R2231",
            "display": "Localized swelling, mass and lump, right upper limb"
        }
    ],
    "R233": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R233",
        "display": "Spontaneous ecchymoses"
    },
    "R509": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R509",
        "display": "Fever, unspecified"
    },
    "R542": [],
    "R5450": [],
    "R682": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R682",
        "display": "Dry mouth, unspecified"
    },
    "R6881": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R6881",
        "display": "Early satiety"
    },
    "R7982": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R7982",
        "display": "Elevated C-reactive protein (CRP)"
    },
    "R87810": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "R87810",
        "display": "Cervical high risk human papillomavirus (HPV) DNA test positive"
    },
    "S72142A": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "S72142A",
        "display": "Displaced intertrochanteric fracture of left femur, initial encounter for closed fracture"
    },
    "S8290XA": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "S8290XA",
        "display": "Unspecified fracture of unspecified lower leg, initial encounter for closed fracture"
    },
    "S93691D": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "S93691D",
        "display": "Other sprain of right foot, subsequent encounter"
    },
    "T781XXD": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "T781XXD",
        "display": "Other adverse food reactions, not elsewhere classified, subsequent encounter"
    },
    "T783": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T783XXS",
            "display": "Angioneurotic edema, sequela"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T783XXA",
            "display": "Angioneurotic edema, initial encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T783XXD",
            "display": "Angioneurotic edema, subsequent encounter"
        }
    ],
    "T784": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XA",
            "display": "Allergy, unspecified, initial encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XD",
            "display": "Allergy, unspecified, subsequent encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XS",
            "display": "Allergy, unspecified, sequela"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7841XA",
            "display": "Arthus phenomenon, initial encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7841XD",
            "display": "Arthus phenomenon, subsequent encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7841XS",
            "display": "Arthus phenomenon, sequela"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7849XA",
            "display": "Other allergy, initial encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7849XD",
            "display": "Other allergy, subsequent encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7849XS",
            "display": "Other allergy, sequela"
        }
    ],
    "T7840": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XA",
            "display": "Allergy, unspecified, initial encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XD",
            "display": "Allergy, unspecified, subsequent encounter"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "T7840XS",
            "display": "Allergy, unspecified, sequela"
        }
    ],
    "T7840XA": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "T7840XA",
        "display": "Allergy, unspecified, initial encounter"
    },
    "Z0989": [],
    "Z1289": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Z1289",
        "display": "Encounter for screening for malignant neoplasm of other sites"
    },
    "Z7409": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Z7409",
        "display": "Other reduced mobility"
    },
    "Z87892": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Z87892",
        "display": "Personal history of anaphylaxis"
    },
    "Z88": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z887",
            "display": "Allergy status to serum and vaccine status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z881",
            "display": "Allergy status to other antibiotic agents status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z880",
            "display": "Allergy status to penicillin"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z882",
            "display": "Allergy status to sulfonamides"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z883",
            "display": "Allergy status to other anti-infective agents status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z883",
            "display": "Allergy status to other anti-infective agents"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z884",
            "display": "Allergy status to anesthetic agent status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z884",
            "display": "Allergy status to anesthetic agent"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z885",
            "display": "Allergy status to narcotic agent status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z885",
            "display": "Allergy status to narcotic agent"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z886",
            "display": "Allergy status to analgesic agent status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z886",
            "display": "Allergy status to analgesic agent"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z887",
            "display": "Allergy status to serum and vaccine"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z888",
            "display": "Allergy status to other drugs, medicaments and biological substances status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z888",
            "display": "Allergy status to other drugs, medicaments and biological substances"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z889",
            "display": "Allergy status to unspecified drugs, medicaments and biological substances"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z889",
            "display": "Allergy status to unspecified drugs, medicaments and biological substances status"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z881",
            "display": "Allergy status to other antibiotic agents"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z882",
            "display": "Allergy status to sulfonamides status"
        }
    ],
    "Z9081": {
        "system": "http://hl7.org/fhir/sid/icd-10-cm",
        "code": "Z9081",
        "display": "Acquired absence of spleen"
    },
    "Z9101": [
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91011",
            "display": "Allergy to milk products"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91010",
            "display": "Allergy to peanuts"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91012",
            "display": "Allergy to eggs"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91013",
            "display": "Allergy to seafood"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91014",
            "display": "Allergy to mammalian meats"
        },
        {
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "code": "Z91018",
            "display": "Allergy to other foods"
        }
    ]
}

to_map = []

icd10_map_file = "../template_migration/mappings/icd10_map.json"
icd10_map = fetch_from_json(icd10_map_file)

with open("PHI/customer_conditions.csv", "r") as file:
	reader = csv.DictReader(file, delimiter=',')
	for row in reader:
		icd10_code = row["ICD-10 Code"].replace(".", "").replace("-", "")
		if icd10_code in icd10_map:
			continue

		if icd10_code in _map:
			item = {
				"Name": row['Name'],
				"ICD-10 Code": row['ICD-10 Code'],
				"options": "\n".join([f"{i['code']} {i['display']}" for i in _map[icd10_code]])
			}
			if item not in to_map:
				to_map.append(item)


headers = {
    "Name",
    "ICD-10 Code",
    "options",
}

with open('mappings/conditions_to_map.csv', 'w') as f:
    writer = csv.DictWriter(f, fieldnames=headers, delimiter=',')
    writer.writeheader()

    for row in to_map:
        writer.writerow(row)


print(to_map)