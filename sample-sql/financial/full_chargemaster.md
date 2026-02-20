# Full Chargemaster

Retrieves records from the Charge Description Master (CDM) table along with payer-specific charge details.

This gives you a complete view of your fee schedule, including any payer-specific overrides.

## SQL

```sql
SELECT
    cdm.cpt_code AS CPT,
    cdm.name AS charge_name,
    cdm.charge_amount AS charge_amount,
    cdm.eff_date AS charge_startdate,
    cdm.end_date AS charge_enddate,
    t.name AS payor,
    psc.charge_amount AS payorspecific_charge_amount,
    psc.eff_date AS payorspecific_charge_startdate,
    psc.end_date AS payorspecific_charge_enddate,
    psc.part_of_capitated_set AS payorspecific_charge_capitated
FROM
    quality_and_revenue_chargedescriptionmaster cdm
LEFT JOIN public.quality_and_revenue_payorspecificcharge psc ON cdm.id = psc.charge_id
LEFT JOIN public.quality_and_revenue_transactor t ON psc.transactor_id = t.id
ORDER BY
    cdm.id ASC;
```

## Columns Returned

| Column | Description |
|--------|-------------|
| `CPT` | CPT procedure code |
| `charge_name` | Name/description of the charge |
| `charge_amount` | Default charge amount |
| `charge_startdate` | Effective start date of the charge |
| `charge_enddate` | End date of the charge (NULL if still active) |
| `payor` | Payer name (if a payer-specific override exists) |
| `payorspecific_charge_amount` | Payer-specific charge amount |
| `payorspecific_charge_startdate` | Start date of the payer-specific charge |
| `payorspecific_charge_enddate` | End date of the payer-specific charge |
| `payorspecific_charge_capitated` | Whether this charge is part of a capitated set |

## Notes

- CPT codes without any payer-specific overrides will show NULL values in the payer-specific columns.
- A single CPT code may appear on multiple rows if it has overrides for different payers.
