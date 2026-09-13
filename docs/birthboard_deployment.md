# Birthboard deployment requirements

Birthboard posters contain personal information and must never be served by
the generic `/media/` alias. Users must access them through
`/birthboard/media/<record_id>/<image|thumbnail>/`, where Django checks that
the caller is a participant or an active reviewer.

## Apache media isolation

Apply this rule to every public virtual host, including staging and
production HTTPS hosts. It must be evaluated for aliased files as well as
proxied requests:

```apache
<LocationMatch "^/media/birthboard_(images|thumbnails)/">
    Require all denied
</LocationMatch>
```

Keep the existing alias for other `/media/` content. After reloading Apache,
verify that an existing poster returns 403 or 404 through both direct paths,
while its authorized Birthboard URL returns 200:

```text
/media/birthboard_images/<known-file>
/media/birthboard_thumbnails/<known-file>
/birthboard/media/<record-id>/image/
/birthboard/media/<record-id>/thumbnail/
```

## Scheduler and display lock

`python manage.py runscheduler` now collects all decorated periodic jobs
before starting APScheduler. Confirm that the persistent job store contains
at least these jobs after every deployment:

```text
birthboard_nightly_update_2345
birthboard_nightly_retry_0005
birthboard_retry_pending_takedowns
```

The pending-takedown compensation job runs every three minutes. An interactive
revoke or rejection still attempts its first takedown immediately after the
database transaction commits.

The web and scheduler containers must mount the same
`/var/tmp/django_cache` directory. The Birthboard display lock uses an atomic
file lock in that directory; separate, unshared directories do not coordinate
the two processes.

Before enabling the public entry point, perform one staging takedown and
upload with real `shihannet` configuration, then confirm the database state,
both playlists, the material library, and the `nightly_display_sync` audit
records agree.

## Required production limits

Existing `config.json` files are intentionally never overwritten by repository
updates. Verify these values explicitly before deployment; older development
configurations may contain load-test values that disable the safeguards:

```json
{
    "birthboard": {
        "max_senders": 20,
        "max_per_receiver_per_date": 10,
        "like_daily_limit": 100,
        "batch_atomic": false,
        "protocol_version": 1
    }
}
```

Increasing `protocol_version` requires every user to sign the updated contract
again. Restart both web and scheduler processes after changing configuration,
because settings are resolved and cached lazily in each process.
