import { timestampText, utcOffset, type TimestampStyle } from '../lib/timestamps';

function renderTimestamps(root: ParentNode) {
  root.querySelectorAll<HTMLTimeElement>('time[data-timestamp]').forEach((element) => {
    const iso = element.dateTime;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return;
    const text = element.querySelector('span');
    const offset = element.querySelector('sup');
    const label = timestampText(iso, element.dataset.timestamp as TimestampStyle);
    const suffix = ` ${utcOffset(date)}`;
    if (text && text.textContent !== label) text.textContent = label;
    if (offset && offset.textContent !== suffix) offset.textContent = suffix;
  });
}

renderTimestamps(document);
// Admin lists and revision dialogs are inserted after the initial page render.
new MutationObserver(() => renderTimestamps(document)).observe(document.body, {
  childList: true,
  subtree: true,
});
