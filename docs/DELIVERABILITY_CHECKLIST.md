# Cold email deliverability checklist

Practitioner checklist. Numbers are common conservative defaults, not guarantees; trust your own bounce and
spam-placement data over this page. Check provider sender rules (Google, Microsoft, Yahoo) before launch.

## Domains and inboxes
- [ ] Separate sending domains (never the main `hostop` domain). Lookalike domains redirect to the main site.
- [ ] 2-3 inboxes per sending domain, real sender names, profile photo, signature with postal address.
- [ ] `hostop dns-check <domain>...` passes: MX, one SPF record (no `+all`), DKIM on your provider's selector,
      DMARC with `p=` and a `rua=` reporting address. Start DMARC at `p=none`, move to `quarantine` once clean.
- [ ] Custom tracking domain if you track clicks; consider no open/click tracking at all for first touches.

## Warm-up
- [ ] 14 days of warm-up before any cold email (`hostop warmup` prints a schedule).
- [ ] Ramp: ~5 cold/inbox/day, +3 per week, cap ~30/inbox/day. Keep warm-up running alongside.
- [ ] No sending on weekends during ramp.

## List quality
- [ ] Only verified emails (the enrichment waterfall drops anything not verified).
- [ ] Re-verify right before export (`hostop export --verify`); catch-all and unknown are excluded.
- [ ] Suppression list applied (opt-outs, bounces, customers, do-not-contact).
- [ ] Bounce rate under ~2% per campaign; pause and investigate above that.

## Content
- [ ] Plain text, no images or attachments in first touch, at most one link (ideally none).
- [ ] Draft passed the validator (length, banned phrases, no invented claims, opt-out line present).
- [ ] Physical postal address in signature (CAN-SPAM) and a clear opt-out honoured within 10 business days.
- [ ] CASL / GDPR contacts reviewed before export (`--include-review` is a deliberate choice).

## Monitoring
- [ ] Google Postmaster Tools and Microsoft SNDS set up for sending domains.
- [ ] Weekly: spam complaints, bounces, reply rate by domain/inbox; rest any inbox that degrades.
