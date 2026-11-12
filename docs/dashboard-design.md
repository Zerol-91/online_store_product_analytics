# Dashboard and chart design

The dashboard will support one decision: which purchase-journey improvement should be tested first? A secondary section will compare repeat purchasing in Black Friday and nearby weekly cohorts. No charts or findings have been computed yet.

## Message before chart

The design follows Gene Zelazny's sequence: define the message, identify the comparison, then choose the chart form. The publisher's [book excerpt](https://www.mann-ivanov-ferber.ru/assets/files/bookparts/026/diagrammy_read.pdf) describes component, item, time, frequency, and correlation comparisons. Chart choices below apply that framework to this analysis; they are not reproductions of the book's figures.

An exploratory chart starts with a neutral question. A final chart title states only a supported finding. Do not write a conclusion first and select data to fit it.

| Analysis question | Comparison | Proposed chart | Required context |
|---|---|---|---|
| Where does the observed journey narrow? | Item comparison of ordered stages | Horizontal bars from a common zero baseline | Session counts, step conversion, event order, tracking coverage |
| Which segments have higher cart abandonment? | Item comparison | Sorted dot plot with confidence intervals; bar/table fallback in BI | Group size, denominator, user clustering, exploratory status |
| How does purchase activity change over time? | Time comparison | Daily line with Black Friday annotated | UTC, complete days, separate scales/panels for different units |
| When do users make their first observed purchase? | Frequency comparison | Histogram or empirical cumulative distribution | Observation limits, nonpurchasers, horizon; optional first-version figure |
| How do repurchase rates evolve across cohorts? | Time comparison across cohort age | M1/M2 heatmap plus cohort size | Calendar definition; incomplete cells shown as NA |
| Do Black Friday buyers repurchase differently? | Time comparison on a common follow-up horizon | Cumulative repeat-purchase curves over days 1–60 | Same mature population, cohort sizes, uncertainty, noncausal interpretation |

Use composition charts only for an actual part-to-whole question. A funnel does not need a decorative trapezoid shape, and a correlation chart is not required unless the research question calls for one.

## One-page layout

1. **Recommendation and KPIs:** one prioritized hypothesis, cart-to-purchase conversion, 30-day repeat rate, and an explicitly labeled revenue scenario.
2. **Ordered session funnel:** step counts, conversion, and tracking coverage.
3. **Cart abandonment by segment:** new/returning status and frozen price groups.
4. **Purchase cohorts:** calendar-month repurchase heatmap with cohort sizes.
5. **Black Friday comparison:** cumulative repeat-purchase curves on matched horizons.

Supporting diagnostics and intervals remain available in tables/notebook when the selected Metabase version cannot display a particular chart element.

## Presentation rules

- Public labels, captions, dashboard text, and notebook narrative are in English.
- Use a light background, readable dark text, blue `#2563EB` for a baseline, amber `#B45309` for a selected comparison, and neutral gray for context. Adapt to the supported BI settings.
- Encode important distinctions with direct labels or line styles as well as color.
- Use one sequential heatmap scale; reserve a visibly separate style for missing follow-up.
- Show units, denominator, date range, and source. Use percentage points for absolute rate differences.
- Start bars at zero; use comparable axes across panels. Avoid 3D, unnecessary dual axes, and decorative chart elements.
- Annotate the finding and show uncertainty. Clearly distinguish scenario assumptions from observed values.
- Keep final README figures readable at normal page width and export them as PNG/SVG from the same reporting tables used by BI.

## Filter semantics

Use session-entry dates for session analysis and first-purchase dates for cohort analysis. Date filters must not remove follow-up events needed to measure an outcome. Connect each filter only to compatible cards, and make the active population explicit. Avoid a global date filter that silently changes the fixed Black Friday comparison.

## Final report

The finished README will lead with the business question, the measured finding, and the recommended next action, followed by two or three supporting figures. The methodology explains definitions and limitations; reproduction instructions document commands that have actually been verified.
