import html2text
import os
import requests
import time

from bs4 import BeautifulSoup


context_urls = [
    "https://docs.canvasmedical.com/sdk/",
    "https://docs.canvasmedical.com/sdk/caching/",
    "https://docs.canvasmedical.com/sdk/canvas_cli/",
    "https://docs.canvasmedical.com/sdk/commands/",
    "https://docs.canvasmedical.com/sdk/data/",
    "https://docs.canvasmedical.com/sdk/data-allergy-intolerance/",
    "https://docs.canvasmedical.com/sdk/data-appointment/",
    "https://docs.canvasmedical.com/sdk/data-banner-alert/",
    "https://docs.canvasmedical.com/sdk/data-billing-line-item/",
    "https://docs.canvasmedical.com/sdk/data-canvasuser/",
    "https://docs.canvasmedical.com/sdk/data-care-team/",
    "https://docs.canvasmedical.com/sdk/data-command/",
    "https://docs.canvasmedical.com/sdk/data-enumeration-types/",
    "https://docs.canvasmedical.com/sdk/data-condition/",
    "https://docs.canvasmedical.com/sdk/data-coverage/",
    "https://docs.canvasmedical.com/sdk/data-detected-issue/",
    "https://docs.canvasmedical.com/sdk/data-device/",
    "https://docs.canvasmedical.com/sdk/data-imaging/",
    "https://docs.canvasmedical.com/sdk/data-labs/",
    "https://docs.canvasmedical.com/sdk/data-lab-partner-and-test/",
    "https://docs.canvasmedical.com/sdk/data-medication/",
    "https://docs.canvasmedical.com/sdk/data-message/",
    "https://docs.canvasmedical.com/sdk/data-note/",
    "https://docs.canvasmedical.com/sdk/data-observation/",
    "https://docs.canvasmedical.com/sdk/data-organization/",
    "https://docs.canvasmedical.com/sdk/data-patient/",
    "https://docs.canvasmedical.com/sdk/data-practicelocation/",
    "https://docs.canvasmedical.com/sdk/data-protocol-override/",
    "https://docs.canvasmedical.com/sdk/data-questionnaire",
    "https://docs.canvasmedical.com/sdk/data-reason-for-visit/",
    "https://docs.canvasmedical.com/sdk/data-staff",
    "https://docs.canvasmedical.com/sdk/data-task",
    "https://docs.canvasmedical.com/sdk/data-team",
    "https://docs.canvasmedical.com/sdk/data-user",
    "https://docs.canvasmedical.com/sdk/data-value-sets/",
    "https://docs.canvasmedical.com/sdk/effects/",
    "https://docs.canvasmedical.com/sdk/effect-protocol-cards/",
    "https://docs.canvasmedical.com/sdk/effect-banner-alerts/",
    "https://docs.canvasmedical.com/sdk/effect-billing-line-items/",
    "https://docs.canvasmedical.com/sdk/form-result-effect",
    "https://docs.canvasmedical.com/sdk/patient-metadata-create-form-effect",
    "https://docs.canvasmedical.com/sdk/layout-effect/",
    "https://docs.canvasmedical.com/sdk/effect-questionnaires/",
    "https://docs.canvasmedical.com/sdk/effect-tasks/",
    "https://docs.canvasmedical.com/sdk/patient-portal/",
    "https://docs.canvasmedical.com/sdk/effect-patient/",
    "https://docs.canvasmedical.com/sdk/effect-notes/",
    "https://docs.canvasmedical.com/sdk/effect-messages/",
    "https://docs.canvasmedical.com/sdk/events/",
    "https://docs.canvasmedical.com/sdk/handlers/",
    "https://docs.canvasmedical.com/sdk/handlers-action-buttons/",
    "https://docs.canvasmedical.com/sdk/handlers-applications/",
    "https://docs.canvasmedical.com/sdk/handlers-basehandler/",
    "https://docs.canvasmedical.com/sdk/handlers-crontask/",
    "https://docs.canvasmedical.com/sdk/handlers-simple-api/",
    "https://docs.canvasmedical.com/sdk/handlers-simple-api-http/",
    "https://docs.canvasmedical.com/sdk/handlers-simple-api-websocket/",
    "https://docs.canvasmedical.com/sdk/protocols/",
    "https://docs.canvasmedical.com/sdk/utils/",
    "https://docs.canvasmedical.com/sdk/questionnaires/",
    "https://docs.canvasmedical.com/sdk/secrets/",
    "https://docs.canvasmedical.com/guides/your-first-plugin/",
    "https://docs.canvasmedical.com/guides/custom-landing-page/",
    "https://docs.canvasmedical.com/guides/creating-webhooks-with-the-canvas-sdk/",
    "https://docs.canvasmedical.com/guides/customize-search-results/",
    "https://docs.canvasmedical.com/guides/embedding-a-smart-on-fhir-application/",
    "https://docs.canvasmedical.com/guides/scribe-ai-parser/",
    "https://docs.canvasmedical.com/guides/patient-portal-forms/",
    "https://docs.canvasmedical.com/guides/improve-hcc-coding-accuracy/",
    "https://docs.canvasmedical.com/guides/staying-on-top-of-tasks/",
    "https://docs.canvasmedical.com/guides/tailoring-the-chart-to-the-patient/",
    "https://docs.canvasmedical.com/guides/growth-charts/",
    "https://docs.canvasmedical.com/guides/your-first-application/",
    "https://docs.canvasmedical.com/guides/profile-additional-fields/"
]

# Unique output filename suffix via timestamp
output_file = f'coding_agent_context_{int(time.time())}.txt'

t0 = int(time.time())
print(f'Starting at {t0}, writing to {output_file}')

n = 0
t = len(context_urls)
failed_urls = []
with open(output_file, 'a') as f:
    for url in context_urls:
        n += 1
        print(f'On url {n} of {t} {url}...', end="")
        resp = requests.get(url)
        if resp.status_code != 200:
            message = f'{resp.status_code} on {url}'
            print(message)
            failed_urls.append(message)
            continue

        soup = BeautifulSoup(resp.text, 'html.parser')
        content_div = soup.find('div', class_='pagelayout__centerdocs__content')
        inner_html = content_div.decode_contents() if content_div else ''
        markdown = html2text.html2text(inner_html)
        dense_markdown = '\n'.join([line for line in markdown.splitlines() if line.strip() != ''])
        
        f.write(f'\n\n\n----- BEGIN PAGE {url}\n')
        f.write(dense_markdown)
        f.write(f'----- END PAGE {url}')
        
        print(f'Wrote {len(markdown.splitlines())} lines.')
        print(f'TIME: {int(time.time())-t0} seconds have elapsed')

    print(f"Output is located at {f.name}")

if failed_urls:
    print('You need to update these urls in your list:')
    print('\n'.join(failed_urls))
