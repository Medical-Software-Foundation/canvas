# Role-Based Homepage

Send each staff member straight to the screen that matters for their job the moment they log in - providers to the schedule, billers to revenue, panel managers to the patient list.

## The problem

Out of the box, everyone lands on the same default homepage after login, so most people start each day by clicking away to the screen they actually use. Teams that want role-appropriate landing pages otherwise have to build and maintain a separate plugin per role or per customer.

## What it does

Routes each user to the right starting page based on their staff role. You decide which role goes where with a single piece of configuration - no code changes to adjust the routing. If someone holds several roles, the most senior one decides where they land, and an optional catch-all covers everyone else.

## Who it's for

Any practice that wants different staff to start on different screens. It works across every role, clinical and administrative:

- Providers and clinical support to the schedule
- Front desk and office managers to the schedule
- Panel and cohort managers to the patient list
- Billing and finance to revenue
- Developers and integration admins to data integration

The mapping is fully configurable - that list is just a sensible starting point.

## Good to know

- Routing is set with one configuration value, so you can adjust it any time without a new release.
- A role can be sent to a built-in page or to a custom plugin application.
- This only changes the landing page. It is not a security boundary - Canvas authorization still governs access to every page.
