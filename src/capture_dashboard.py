"""Check the rendered dashboard and capture its main analytical sections."""

import argparse
import json
import sys

from playwright.sync_api import sync_playwright, Error as BrowserError

from local_config import ROOT
from metabase_client import MetabaseError, authenticated_client
from setup_metabase import REPORT, load_manifest


def capture(channel='msedge'):
    client = authenticated_client()
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    validation = json.loads((ROOT/'data/reports/metabase_validation.json').read_text(encoding='utf-8'))
    if not validation['all_checks_passed']:
        raise ValueError('Validate the real dashboard before capture.')
    failures = []
    manifest = load_manifest()
    headings = {item['key']: item['text'].splitlines()[0].lstrip('# ') for item in manifest['text']}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel, headless=True)
        context = browser.new_context(viewport={'width': 1600, 'height': 6000}, device_scale_factor=1,
                                      locale='en-US', timezone_id='UTC')
        context.add_cookies([{'name': 'metabase.SESSION', 'value': client.token, 'url': client.base_url,
                             'httpOnly': True, 'sameSite': 'Lax'}])
        page = context.new_page()
        page.on('response', lambda response: failures.append(response.status)
                if '/api/' in response.url and response.status >= 400 else None)
        page.goto(report['dashboard_url'] + '?episode_order=allow_equal&purchase_month=',
                  wait_until='networkidle', timeout=90000)
        page.get_by_role('heading', name=headings['decision'], exact=True).wait_for(timeout=60000)
        cards = page.locator('[data-testid="dashcard"]')
        cards.first.wait_for(timeout=60000)
        for index in range(cards.count()):
            cards.nth(index).scroll_into_view_if_needed()
            page.wait_for_load_state('networkidle')
        page.evaluate('document.fonts.ready')
        if failures:
            raise ValueError('Dashboard has failed API requests; inspect locally before publication.')
        errors = page.get_by_text('There was a problem displaying this chart.', exact=False)
        if errors.count():
            raise ValueError('A dashboard visualization failed to render.')
        width_checks = []
        for width in (1366, 1600, 1920):
            page.set_viewport_size({'width': width, 'height': 6000})
            page.wait_for_load_state('networkidle')
            for item in manifest['text']:
                if item['key'] == 'limitations':
                    continue
                heading = page.get_by_role('heading', name=headings[item['key']], exact=True)
                outer = heading.locator('xpath=ancestor::*[@data-testid="dashcard"]')
                clipped = outer.evaluate('''element => {
                    const box = element.getBoundingClientRect();
                    return [...element.querySelectorAll('h1,h2,h3,p')].some(node => {
                        const child = node.getBoundingClientRect();
                        return child.bottom > box.bottom - 4 || child.right > box.right + 1;
                    });
                }''')
                if clipped:
                    raise ValueError(f'Text clipping at {width}px: ' + item['key'])
            width_checks.append({'width': width, 'text_fits': True})
        page.set_viewport_size({'width': 1600, 'height': 6000})
        destination = ROOT/'docs/img'
        destination.mkdir(parents=True, exist_ok=True)
        # Clip the real dashboard; no charts or values are drawn separately.
        sections = [
            ('dashboard_overview.png', headings['decision'], headings['segments_heading']),
            ('dashboard_segments.png', headings['segments_heading'], headings['calendar_heading']),
            ('dashboard_cohorts.png', headings['calendar_heading'], headings['scenario_heading']),
            ('dashboard_experiment.png', headings['scenario_heading'], None),
        ]
        page.evaluate('window.scrollTo(0, 0)')
        for filename, start, end in sections:
            first = page.get_by_role('heading', name=start, exact=True).first
            first.scroll_into_view_if_needed()
            start_box = first.bounding_box()
            scroll_y = page.evaluate('window.scrollY')
            y = max(0, start_box['y'] + scroll_y - 20)
            if end:
                bottom = page.get_by_role('heading', name=end, exact=True).bounding_box()['y'] + scroll_y - 20
            else:
                box = cards.last.bounding_box()
                bottom = box['y'] + scroll_y + box['height'] + 4
            page.screenshot(path=str(destination/filename), full_page=True,
                            clip={'x': 16, 'y': y, 'width': 1568, 'height': bottom-y})
        result = {'rendered_cards': cards.count(), 'failed_api_requests': failures, 'width_checks': width_checks,
                  'screenshots': [item[0] for item in sections]}
        (ROOT/'data/reports/metabase_browser.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        browser.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--channel', default='msedge', choices=('msedge', 'chrome', 'chromium'))
    args = parser.parse_args()
    try:
        result = capture(args.channel)
    except (OSError, ValueError, KeyError, MetabaseError, BrowserError) as error:
        print(f'Dashboard capture failed: {error}', file=sys.stderr)
        return 1
    print(f"Captured {len(result['screenshots'])} dashboard sections; {result['rendered_cards']} cards rendered.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
