import { afterEach, describe, expect, it, vi } from 'vitest';
import { dateInput, formatTimestamp, inputToUtc, timestampText, utcOffset } from './timestamps';
import { html, raw } from './dom';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('UTC timestamps', () => {
  it('converts positive, negative and fractional offsets without losing seconds', () => {
    const instant = '2026-12-31T20:30:45Z';
    for (const zone of ['0', '480', '-210', '345', 'local']) {
      expect(inputToUtc(dateInput(instant, zone), zone)).toBe(instant);
    }
    expect(dateInput(instant, '480')).toBe('2027-01-01T04:30:45');
    expect(inputToUtc('2027-01-01T04:30:45', '480')).toBe(instant);
    expect(inputToUtc('', '0')).toBeNull();
    expect(() => inputToUtc('invalid', '0')).toThrow();
  });

  it('renders a UTC server fallback with an explicit superscript', () => {
    const markup = formatTimestamp('2026-12-31T20:30:45Z', 'datetime');
    expect(markup).toContain('datetime="2026-12-31T20:30:45Z"');
    expect(markup).toContain('<sup> UTC+0</sup>');
    expect(timestampText('2026-12-31T20:30:45Z', 'year', false)).toContain('2026');
    expect(String(html`${raw(markup)}`)).toBe(markup);
    expect(formatTimestamp('invalid')).toBe('—');
  });

  it('labels quarter-hour offsets and uses the timestamp date for DST', () => {
    vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-345);
    expect(utcOffset(new Date())).toBe('UTC+5.75');
    vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(210);
    expect(utcOffset(new Date())).toBe('UTC-3.5');
    vi.spyOn(Date.prototype, 'getTimezoneOffset').mockReturnValue(-480);
    expect(utcOffset(new Date())).toBe('UTC+8');
  });

  it('renders the client date and its corresponding offset together', () => {
    vi.stubGlobal('window', {});
    const iso = '2026-12-31T20:30:45Z';
    expect(formatTimestamp(iso, 'datetime')).toContain(timestampText(iso, 'datetime'));
    expect(formatTimestamp(iso)).toContain(`<sup> ${utcOffset(new Date(iso))}</sup>`);
  });

  it.runIf(Intl.DateTimeFormat().resolvedOptions().timeZone === 'America/New_York')(
    'handles DST offsets and rejects the missing spring hour',
    () => {
      expect(utcOffset(new Date('2026-01-01T12:00:00Z'))).toBe('UTC-5');
      expect(utcOffset(new Date('2026-07-01T12:00:00Z'))).toBe('UTC-4');
      expect(() => inputToUtc('2026-03-08T02:30', 'local')).toThrow();
      expect(inputToUtc('2026-03-08T02:30', '-300')).toBe('2026-03-08T07:30:00Z');
    },
  );
});
