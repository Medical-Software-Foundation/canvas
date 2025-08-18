-- Retrieves all unlocked notes before today, including creation date, service date, state, practice location, originator, and provider details.

SELECT
    -- Note details
    n.created AS note_created,
    n.datetime_of_service,
    nsc.state AS note_state,

    -- Practice location
    pl.full_name AS practice_location,

    -- Staff details
    s1.first_name || ' ' || s1.last_name AS originator_name,
    s2.first_name || ' ' || s2.last_name AS provider_name
FROM
    api_note n
-- Links notes to their most recent state change event
JOIN (
    SELECT
        MAX(id) AS max_id,
        note_id
    FROM
        api_notestatechangeevent
    GROUP BY
        note_id
) max_nsc ON max_nsc.note_id = n.id
JOIN api_notestatechangeevent nsc ON nsc.id = max_nsc.max_id
-- Links notes to practice locations
JOIN api_practicelocation pl ON pl.id = n.location_id
-- Links notes to their originators
JOIN api_staff s1 ON s1.user_id = n.originator_id
-- Links notes to their providers
JOIN api_staff s2 ON s2.id = n.provider_id
-- Links notes to patients
JOIN api_patient p ON p.id = n.patient_id
WHERE
    -- Include only notes with a service date before today
    n.datetime_of_service < current_date
    -- Exclude notes in the following states: Deleted (DLT), Locked (LKD), or Cancelled (CLD)
    AND nsc.state NOT IN ('DLT', 'LKD', 'CLD');
