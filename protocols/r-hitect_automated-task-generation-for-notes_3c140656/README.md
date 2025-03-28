# Summary of the Protocol: Automated Task Generation for Incomplete or Incorrectly Coded Notes

The end goal of this protocol is to streamline the management of patient notes by care navigators, ensuring that notes are either closed with the required coding or updated appropriately, thereby reducing billing workflow issues.

The protocol targets care navigators using the Canvas platform to manage patient notes. It focuses on notes that are left open beyond a predefined time frame or closed without the necessary coding. The protocol recommends implementing a monitoring system to track these notes, automatically generating tasks for care navigators to address the issues, and setting deadlines to ensure timely resolution.

## Important Information:

- **Initial Population**: All care navigators using the Canvas platform for managing patient notes.
  
- **Subset in Consideration**: 
  - Notes left open beyond a predefined time frame after the session date/time.
  - Notes closed without the required coding.

- **Exclusion Criteria**:
  - Notes closed with all required coding within the predefined time frame.
  - Notes intentionally left open due to ongoing patient care activities, as documented by the care navigator.

- **Actions Required**:
  1. **Diagnostic**:
     - Implement a monitoring system using Canvas SDK plugins to track note status.
     - Identify notes that meet the criteria for being left open too long or closed without coding.
  
  2. **Administrative**:
     - Automatically generate a task within the Canvas platform for each identified note.
     - Assign the task to the care navigator who owns the note.
  
  3. **Therapeutic**:
     - Notify the care navigator of the task, prompting them to close the note with the required coding or update the note status.
  
  4. **Completion**:
     - Set a completion deadline for the task to ensure timely resolution.
     - Monitor task completion and provide feedback to care navigators to improve compliance and reduce billing workflow issues.

- **Definition of Done**:
  - A new task is successfully created and assigned in Canvas for each note that meets the criteria.
  - The care navigator receives a notification and resolves the task by either closing the note with the required coding or updating the note status within the set deadline.
  - Reduction in billing workflow issues related to incomplete or incorrectly coded notes.