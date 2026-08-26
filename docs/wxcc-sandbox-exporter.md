Our goal today is to build a utility to selectively export the configuration of an expiring Webex Contact Center sandbox, somewhat following the example of Unified Communications Manager (<https://www.cisco.com/c/en/us/td/docs/voice_ip_comm/cucm/bat/12_5_SU6/cucm_b_bulk-administration-guide-1251su6/cucm_b_bulk-administration-guide-1251su2_chapter_0111110.html>).

Then a facility to import into a new sandbox tenant.

The utility should use oAuth2 authentication, with the option to use a personal bearer token if desired via changes to an environment file. But oAuth2 should always be default. It should determine the tenant based upon the org ID in the oAuth2 token or in the personal bearer token.

Name the export file &lt;tenant&gt;-export (for example, my sandbox tenant name is davidwolgast-8xgo, so name the file "davidwolgast-8xgo-export" and use a compressed file format such as zip or tar

Import should ingest the export file natively and offer the choice of which objects to import, or an option to import all objects.

Export the following (only non-default (items which automatically are built in the tenant at provisioning) if possible):

**Webex Calling**

- Non-default Feature Configuration
- Non-default Calling Settings

**Contact Center**

- **Customer Experience**
  - Channels
  - Queues
  - Business Hours
  - Audio Files
  - Flows
    - Flows
    - Subflows
    - Global Variables
  - Functions
  - Surveys
- **User Management**
  - Sites
  - Skill Management (skill configuration)
  - Skill Profiles
  - Teams
  - Access
    - User Profiles
    - Resource Collections
  - Contact Center Users
- **Desktop Experience**
  - Multimedia Profiles
  - Outdial ANI
  - Desktop Layouts
  - Address Books
  - Desktop Profiles
  - Idle/Wrap-up Codes

Use whichever platform/coding framework works best.

Establish a git repo in this folder, as well as a remote public repo on github under my space dwolgast-lab. We can tie this to Vercel using our connector if web-based, or run locally.

Make thorough build and test plans. Use any resources available that we have previously built, like my wxcc-skills MCP that I will connect to this repo (located at c:\\users\\david.wolgast\\source\\repos\\wxcc-skills). I am supplying the openAPI json files for Webex admin, Webex calling, and Webex contact center in the docs folder.

The use scope is that I want any github user to be able to connect this exporter/importer to their old and new sandbox tenants (not simultaneously) and use it.

Note: If this is plausible to create reasonable as a skill, set of skills, or mcp server, let's go that way. But fixed code/CLI/web interface is perfectly acceptable.

As always, don't guess on facts. Any information you use should be able to show a reference. Ask questions for important or user-facing decisions that are unclear, but use best judgement on minor changes/adjustments/decisions.