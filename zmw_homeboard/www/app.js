// After next/prev: how often, and how many times, to look for the new picture
const HB_PHOTO_FOLLOW_MS = 700;
const HB_PHOTO_FOLLOW_TRIES = 6;

class Homeboard extends React.Component {
  static buildProps() {
    return {
      key: 'Homeboard',
    };
  }

  constructor(props) {
    super(props);
    this.state = {
      homeboards: [],
      brokerConnected: true,
      loading: true,
      // One announcement is sent to every homeboard at once
      announceMsg: '',
      announceSecs: 60,
      announceStatus: null,
      // One album filter applies to every homeboard, like an announcement
      albumName: '',
      albumExclude: '',
      albumFromYear: '',
      albumToYear: '',
      albumFilter: null,
      albumFilterStatus: null,
      // Per homeboard, what the transition time box holds
      transitionSecs: {},
      // The homeboard whose page is open, or null for the list of them all.
      // The homeboard's QR code links here with ?hb_id=<id>, which opens its page.
      selectedId: new URLSearchParams(window.location.search).get('hb_id') || Homeboard.hbIdFromHash(),
    };
    this.refresh = this.refresh.bind(this);
    this.onHashChange = this.onHashChange.bind(this);
    this.announceAll = this.announceAll.bind(this);
    this.clearAnnounce = this.clearAnnounce.bind(this);
    this.applyAlbumFilter = this.applyAlbumFilter.bind(this);
    this.clearAlbumFilter = this.clearAlbumFilter.bind(this);
    // The boxes are seeded once from whatever filter is in force; after that
    // they're the user's to type in, and the 5s refresh must not stomp them
    this._albumBoxesSeeded = false;
    this._poller = null;
    // hb id -> timer of the refresh waiting for its next/prev picture
    this._photoFollow = {};
  }

  componentDidMount() {
    // A QR link becomes the same #hb=<id> the list links to, so going back
    // from that page lands on the list, and a reload doesn't reopen it
    if (new URLSearchParams(window.location.search).has('hb_id')) {
      const hash = this.state.selectedId ? Homeboard.hbHash(this.state.selectedId) : '';
      window.history.replaceState(null, '', `${window.location.pathname}${hash}`);
    }
    window.addEventListener('hashchange', this.onHashChange);
    this.refresh();
    this._poller = mPoll(this.refresh, 5000);
  }

  componentWillUnmount() {
    window.removeEventListener('hashchange', this.onHashChange);
    this._poller?.stop();
    Object.values(this._photoFollow).forEach(clearTimeout);
    this._photoFollow = {};
  }

  // A homeboard's page lives at #hb=<id>, so the back button and bookmarks work
  static hbHash(hbId) {
    return `#hb=${encodeURIComponent(hbId)}`;
  }

  static hbIdFromHash() {
    const m = /(?:^#|&)hb=([^&]*)/.exec(window.location.hash);
    if (!m) return null;
    try {
      return decodeURIComponent(m[1]) || null;
    } catch (e) {
      return null;
    }
  }

  onHashChange() {
    this.setState({ selectedId: Homeboard.hbIdFromHash() });
    window.scrollTo(0, 0);
  }

  // The thumbnail of the picture a homeboard has on screen, or null if it isn't
  // showing an Immich picture. It's by Immich asset id, so each picture has its
  // own URL, the same on every homeboard: the browser caches it once.
  static thumbUrl(hb) {
    const id = hb.displayed_photo && hb.displayed_photo.id;
    if (typeof id !== 'string' || !id) return null;
    return `/thumbnail_immich/${encodeURIComponent(id)}`;
  }

  // onDone, if given, runs once the new state is rendered (or the fetch failed)
  refresh(onDone) {
    const done = (typeof onDone === 'function') ? onDone : undefined;
    mJsonGet('/get_homeboards_state', (data) => {
      const homeboards = (data && data.homeboards) || [];
      const albumFilter = (data && data.album_filter) || null;
      const brokerConnected = !data || data.broker_connected !== false;
      this.setState({ homeboards, albumFilter, brokerConnected, loading: false }, done);
      if (albumFilter && !this._albumBoxesSeeded) {
        this._albumBoxesSeeded = true;
        this.setState({
          albumName: albumFilter.name || '',
          albumExclude: albumFilter.exclude || '',
          albumFromYear: albumFilter.from_year || '',
          albumToYear: albumFilter.to_year || '',
        });
      }
    }, () => {
      this.setState({ loading: false }, done);
    });
  }

  // Commands are the same ones the MQTT interface offers; the service
  // forwards them to the homeboard
  sendCmd(hbId, path) {
    const moves = (path === 'next' || path === 'prev');
    const before = moves ? this.photoId(hbId) : null;
    mJsonGet(`/cmd/${encodeURIComponent(hbId)}/${path}`, () => {
      if (moves) this.followPhotoChange(hbId, before);
      else this.refresh();
    });
  }

  photoId(hbId) {
    const hb = this.state.homeboards.find((h) => h.id === hbId);
    return (hb && hb.displayed_photo && hb.displayed_photo.id) || null;
  }

  // A homeboard publishes its new picture a moment after taking next/prev, and
  // more so on a slow device, so the refresh right after the command would
  // still show the old one. Ask again shortly, until the picture changes; past
  // a few tries the normal poll takes over.
  followPhotoChange(hbId, before) {
    clearTimeout(this._photoFollow[hbId]);
    let tries = 0;
    const check = () => {
      tries += 1;
      this.refresh(() => {
        if (this.photoId(hbId) !== before || tries >= HB_PHOTO_FOLLOW_TRIES) {
          delete this._photoFollow[hbId];
          return;
        }
        this._photoFollow[hbId] = setTimeout(check, HB_PHOTO_FOLLOW_MS);
      });
    };
    this._photoFollow[hbId] = setTimeout(check, HB_PHOTO_FOLLOW_MS);
  }

  setTransitionSecs(hbId, value) {
    this.setState((prev) => ({
      transitionSecs: { ...prev.transitionSecs, [hbId]: value },
    }));
  }

  // Whole seconds, at least min; null when the box holds something else, which
  // is what disables the button that would send it
  static seconds(value, min) {
    const secs = parseInt(value, 10);
    return (Number.isFinite(secs) && secs >= min) ? secs : null;
  }

  applyTransitionSecs(hbId) {
    const secs = Homeboard.seconds(this.state.transitionSecs[hbId], 1);
    if (secs === null) return;
    this.sendCmd(hbId, `set_transition_time_secs/${secs}`);
  }

  // An empty message clears whatever is on screen
  sendAnnounce(msg) {
    const secs = Homeboard.seconds(this.state.announceSecs, 0);
    if (secs === null) return;
    mJsonPut('/announce_all', { msg, timeout_secs: secs }, (data) => {
      const sent = (data && data.sent_to) || [];
      const failed = (data && data.failed) || [];
      const what = msg ? `Announced to ${sent.length}` : `Cleared on ${sent.length}`;
      this.setState({
        announceStatus: failed.length ? `${what}, failed on ${failed.join(', ')}` : what,
      });
    }, () => {
      this.setState({ announceStatus: 'Announce failed' });
    });
  }

  announceAll() {
    this.sendAnnounce(this.state.announceMsg.trim());
  }

  clearAnnounce() {
    this.sendAnnounce('');
  }

  renderAnnounce() {
    const { announceMsg, announceSecs, announceStatus } = this.state;
    return (
      <div className="card">
        <h3>Announce</h3>
        <div>Shown on every homeboard at once.</div>
        <div>
          <input
            type="text"
            value={announceMsg}
            placeholder="Message"
            size="40"
            onChange={(e) => this.setState({ announceMsg: e.target.value })}
          />
          <label>
            {' for '}
            <input
              type="number"
              min="0"
              value={announceSecs}
              size="4"
              onChange={(e) => this.setState({ announceSecs: e.target.value })}
            />
            {' s (0 = until cleared) '}
          </label>
          <button
            onClick={this.announceAll}
            disabled={!announceMsg.trim() || Homeboard.seconds(announceSecs, 0) === null}
          >
            Show on all
          </button>
          <button onClick={this.clearAnnounce} disabled={Homeboard.seconds(announceSecs, 0) === null}>
            Clear all
          </button>
        </div>
        {announceStatus && (<div><em>{announceStatus}</em></div>)}
      </div>
    );
  }

  // An empty box means "no bound"; null when it holds something that isn't a
  // year, which is what disables the button that would send it
  static year(value) {
    const s = String(value).trim();
    if (s === '') return 0;
    const y = parseInt(s, 10);
    return (Number.isFinite(y) && y >= 0 && y <= 9999) ? y : null;
  }

  // What the boxes currently describe, or null while they don't describe a
  // filter the service would accept
  albumFilterArgs() {
    const from = Homeboard.year(this.state.albumFromYear);
    const to = Homeboard.year(this.state.albumToYear);
    if (from === null || to === null) return null;
    // The service rejects a reversed range: the year test is an overlap test,
    // so it would select the albums straddling the boundary rather than none
    if (from && to && from > to) return null;
    return {
      name: this.state.albumName.trim(),
      exclude: this.state.albumExclude.trim(),
      from_year: from,
      to_year: to,
    };
  }

  sendAlbumFilter(filt) {
    mJsonPut('/set_album_filter_all', filt, (data) => {
      const sent = (data && data.sent_to) || [];
      const failed = (data && data.failed) || [];
      const what = `Album filter set on ${sent.length}`;
      this.setState({
        albumFilterStatus: failed.length ? `${what}, failed on ${failed.join(', ')}` : what,
      });
      this.refresh();
    }, () => {
      this.setState({ albumFilterStatus: 'Album filter failed' });
    });
  }

  applyAlbumFilter() {
    const filt = this.albumFilterArgs();
    if (filt === null) return;
    this.sendAlbumFilter(filt);
  }

  // An empty filter is the only way back to showing every album
  clearAlbumFilter() {
    this.setState({
      albumName: '', albumExclude: '', albumFromYear: '', albumToYear: '',
    });
    this.sendAlbumFilter({});
  }

  // unset is what a missing filter means where it's shown: nothing sent from
  // here yet, or a device that doesn't report the filter it runs
  static describeAlbumFilter(f, unset = 'not set since this service started') {
    if (!f || typeof f !== 'object') return unset;
    const parts = [];
    if (f.name) parts.push(`named ${f.name}`);
    if (f.exclude) parts.push(`except ${f.exclude}`);
    if (f.from_year) parts.push(`from ${f.from_year}`);
    if (f.to_year) parts.push(`up to ${f.to_year}`);
    return parts.length ? parts.join(', ') : 'every album';
  }

  renderAlbumFilter() {
    const {
      albumName, albumExclude, albumFromYear, albumToYear,
      albumFilter, albumFilterStatus, homeboards,
    } = this.state;
    return (
      <div className="card">
        <h3>Album filter</h3>
        <div>
          Which albums every homeboard may show pictures from. Patterns are
          comma separated and match the whole album name, case insensitive,
          with <code>*</code> for any run of characters and <code>?</code> for
          one. Years bound the dates of an album's pictures, not its name; an
          album is kept when any part of its span falls in the range.
        </div>
        <div>
          <label>
            {' Show '}
            <input
              type="text"
              value={albumName}
              placeholder="every album"
              size="30"
              onChange={(e) => this.setState({ albumName: e.target.value })}
            />
          </label>
          <label>
            {' except '}
            <input
              type="text"
              value={albumExclude}
              placeholder="nothing"
              size="30"
              onChange={(e) => this.setState({ albumExclude: e.target.value })}
            />
          </label>
        </div>
        <div>
          <label>
            {' From year '}
            <input
              type="number"
              min="0"
              max="9999"
              value={albumFromYear}
              size="4"
              placeholder="any"
              onChange={(e) => this.setState({ albumFromYear: e.target.value })}
            />
          </label>
          <label>
            {' to year '}
            <input
              type="number"
              min="0"
              max="9999"
              value={albumToYear}
              size="4"
              placeholder="any"
              onChange={(e) => this.setState({ albumToYear: e.target.value })}
            />
          </label>
          <button onClick={this.applyAlbumFilter} disabled={this.albumFilterArgs() === null}>
            Apply to all
          </button>
          <button onClick={this.clearAlbumFilter}>
            Show all albums
          </button>
        </div>
        <div>Last sent from here: <em>{Homeboard.describeAlbumFilter(albumFilter)}</em></div>
        {/* What each device says it runs, which is what's really in force: a
            device keeps its filter across our restarts, and one that was
            offline missed the last one we sent */}
        <ul>
          {homeboards.map((hb) => (
            <li key={hb.id}>
              {hb.id}: <em>{Homeboard.describeAlbumFilter(
                Homeboard.part(Homeboard.part(hb.device_state, 'slideshow'), 'album_filter'),
                'unknown')}</em>
            </li>
          ))}
        </ul>
        {albumFilterStatus && (<div><em>{albumFilterStatus}</em></div>)}
      </div>
    );
  }

  renderControls(hb) {
    const secs = this.state.transitionSecs[hb.id] ?? '';
    return (
      <div className="hb-actions">
        <button onClick={() => this.sendCmd(hb.id, 'prev')}>&#9664; Previous</button>
        <button onClick={() => this.sendCmd(hb.id, 'next')}>Next &#9654;</button>
        <button onClick={() => this.sendCmd(hb.id, 'force_on')}>Screen on</button>
        <button onClick={() => this.sendCmd(hb.id, 'force_off')}>Screen off</button>
        <label className="hb-sub">
          {' Seconds per picture '}
          <input
            type="number"
            min="1"
            value={secs}
            size="4"
            placeholder="30"
            onChange={(e) => this.setTransitionSecs(hb.id, e.target.value)}
          />
        </label>
        <button
          onClick={() => this.applyTransitionSecs(hb.id)}
          disabled={Homeboard.seconds(secs, 1) === null}
        >
          Set
        </button>
      </div>
    );
  }

  // A device's state record is one JSON object whose values may all be null
  // (unknown, or meaningless on that device), so every part of it is read
  // through this: the sub-object, or null when it's absent or not an object
  static part(obj, key) {
    const v = (obj && typeof obj === 'object') ? obj[key] : null;
    return (v && typeof v === 'object' && !Array.isArray(v)) ? v : null;
  }

  // Seconds from a device's unix timestamp until now, or null without one.
  // Clamped because the device's clock and the browser's needn't agree.
  static secsSince(ts) {
    if (typeof ts !== 'number') return null;
    return Math.max(0, Math.round(Date.now() / 1000 - ts));
  }

  renderOccupancy(occ) {
    if (!occ || typeof occ.occupied !== 'boolean') {
      return (<div>Occupancy: <em>unknown</em></div>);
    }
    // distance_cm is the one extra key a device may add that we know by name
    // (the homeboard's mmWave sensor); it's absent on a Portal
    return (
      <div>
        Occupancy: <strong>{occ.occupied ? 'Occupied' : 'Empty'}</strong>
        {typeof occ.distance_cm === 'number' && (<> — distance {occ.distance_cm} cm</>)}
        {occ.source && (<> (from {occ.source})</>)}
      </div>
    );
  }

  static describeSlideshow(ss) {
    if (!ss || typeof ss.active !== 'boolean') return 'unknown';
    const parts = [ss.active ? 'Active' : 'Not active'];
    if (ss.shown_in) parts.push(`in ${ss.shown_in}`);
    if (ss.night_cover === true) parts.push('covered for the night');
    return parts.join(', ');
  }

  // wanted null means the platform decides; otherwise the device is holding
  // the screen one way, and it not being that way is worth seeing
  static screenWanted(screen) {
    if (!screen || typeof screen.on !== 'boolean') return { wanted: null, mismatch: false };
    const wanted = (screen.wanted === 'on' || screen.wanted === 'off') ? screen.wanted : null;
    return { wanted, mismatch: wanted !== null && (wanted === 'on') !== screen.on };
  }

  renderScreen(screen) {
    if (!screen || typeof screen.on !== 'boolean') {
      return (<div>Screen: <em>unknown</em></div>);
    }
    const since = Homeboard.secsSince(screen.since);
    const reason = screen.wanted_reason ? ` (${screen.wanted_reason})` : '';
    const { wanted, mismatch } = Homeboard.screenWanted(screen);
    return (
      <div>
        Screen: <strong>{screen.on ? 'On' : 'Off'}</strong>
        {since !== null && (<> for {this.formatUptime(since)}</>)}
        {screen.screensaver === true && (<>, screensaver running</>)}
        {wanted !== null && !mismatch && (<> — held {wanted}{reason}</>)}
        {mismatch && (
          <> — <strong className="text-error">should be {wanted}{reason}</strong></>
        )}
      </div>
    );
  }

  // An empty list means the device is fine, so only a non-empty one shows
  renderErrors(errors) {
    if (!Array.isArray(errors) || errors.length === 0) return null;
    return (
      <div className="dash-alert">
        <b>Errors</b>
        <ul>
          {errors.map((e, i) => (
            <li key={i}>
              {(e && typeof e === 'object')
                ? (<>{e.source && (<strong>{e.source}: </strong>)}{String(e.message ?? '')}</>)
                : String(e)}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // What both the list and a homeboard's page say about the picture on screen
  static photoSummary(photo) {
    const geo = photo.reverse_geo || {};
    const gps = photo.gps;
    return {
      album: photo.albumname || null,
      taken: photo['EXIF DateTimeOriginal'] || null,
      location: geo.revgeo || [geo.city, geo.state, geo.country].filter(Boolean).join(', ') || null,
      mapUrl: (gps && gps.lat != null && gps.lon != null)
        ? `https://www.openstreetmap.org/?mlat=${gps.lat}&mlon=${gps.lon}#map=16/${gps.lat}/${gps.lon}`
        : null,
    };
  }

  // EXIF dates look like 2019:04:12 10:22:33; the list only wants the day
  static photoDay(taken) {
    const m = /^(\d{4}):(\d{2}):(\d{2})/.exec(taken || '');
    return m ? `${m[1]}-${m[2]}-${m[3]}` : taken;
  }

  renderLocation(location, mapUrl) {
    return mapUrl
      ? (<a href={mapUrl} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>{location}</a>)
      : location;
  }

  renderDisplayedPhoto(photo) {
    if (!photo) {
      return (<p>No photo info available.</p>);
    }
    const camera = [photo['Image Make'], photo['Image Model']].filter(Boolean).join(' ');
    const w = photo['EXIF ExifImageWidth'];
    const h = photo['EXIF ExifImageLength'];
    const size = (w && h) ? `${w} x ${h}` : null;
    const { taken, location, mapUrl } = Homeboard.photoSummary(photo);
    return (
      <div>
        <dl>
          {photo.albumname && (<><dt>Album</dt><dd>{photo.albumname}</dd></>)}
          {photo.filename && (
            <>
              <dt>File</dt>
              <dd>
                {photo.src_url
                  ? (<a href={photo.src_url} target="_blank" rel="noreferrer">{photo.filename}</a>)
                  : photo.filename}
              </dd>
            </>
          )}
          {taken && (<><dt>Taken</dt><dd>{taken}</dd></>)}
          {camera && (<><dt>Camera</dt><dd>{camera}</dd></>)}
          {size && (<><dt>Size</dt><dd>{size}</dd></>)}
          {location && (
            <>
              <dt>Location</dt>
              <dd>{this.renderLocation(location, mapUrl)}</dd>
            </>
          )}
        </dl>
        <details>
          <summary>Raw metadata</summary>
          <pre>{JSON.stringify(photo, null, 2)}</pre>
        </details>
      </div>
    );
  }

  formatUptime(s) {
    const d = Math.floor(s / 86400);
    const h = Math.floor((s % 86400) / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (d > 0) return `${d}d ${h}h ${m}m`;
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  }

  decodeThrottled(hex) {
    if (hex === undefined || hex === null || hex === '?') {
      return { text: hex ? String(hex) : '?', alert: false };
    }
    const n = parseInt(hex, 16);
    if (Number.isNaN(n)) return { text: String(hex), alert: false };
    if (n === 0) return { text: `all clear (${hex})`, alert: false };
    const now = [];
    if (n & 0x1) now.push('under-voltage');
    if (n & 0x2) now.push('freq capped');
    if (n & 0x4) now.push('throttled');
    if (n & 0x8) now.push('soft temp limit');
    const past = [];
    if (n & 0x10000) past.push('under-voltage');
    if (n & 0x20000) past.push('freq capping');
    if (n & 0x40000) past.push('throttling');
    if (n & 0x80000) past.push('soft temp limit');
    const parts = [];
    if (now.length) parts.push(`now: ${now.join(', ')}`);
    if (past.length) parts.push(`since boot: ${past.join(', ')}`);
    return { text: `${hex} — ${parts.join('; ')}`, alert: now.length > 0 };
  }

  // v==null -> '—' (neutral); otherwise green when it matches the healthy
  // value, red when it doesn't. goodWhenTrue flips which boolean is "healthy".
  boolCell(v, goodWhenTrue = true) {
    if (v == null) return (<span>—</span>);
    const good = goodWhenTrue ? (v === true) : (v === false);
    return (<span className={good ? 'text-primary' : 'text-error'}>{v ? 'yes' : 'no'}</span>);
  }

  // bad is whether the health telemetry is worth a warning
  static doctorStatus(doctor) {
    const tsMs = doctor.ts ? Date.parse(doctor.ts) : NaN;
    const ageSec = Number.isNaN(tsMs) ? null : Math.max(0, Math.round((Date.now() - tsMs) / 1000));
    // No LWT and non-retained: infer liveness from ts. > ~3x the 30s poll = stale.
    const stale = ageSec === null || ageSec > 90;
    return {
      ageSec,
      stale,
      label: stale ? 'stale / unknown' : (doctor.state || 'unknown'),
      bad: stale || doctor.state === 'net_down' || doctor.state === 'degraded',
    };
  }

  renderDeviceHealth(doctor) {
    if (!doctor) {
      return (
        <details>
          <summary>Device health</summary>
          <p>No health telemetry received yet.</p>
        </details>
      );
    }

    const num = (v, unit = '') => (typeof v === 'number' ? `${v}${unit}` : '—');
    const { ageSec, stale, label: statusLabel, bad } = Homeboard.doctorStatus(doctor);
    let statusClass;
    if (stale || doctor.state === 'net_down') statusClass = 'text-error';
    else if (doctor.state === 'ok') statusClass = 'text-primary';

    const throttled = this.decodeThrottled(doctor.throttled);
    const memMb = (typeof doctor.mem_avail_kb === 'number')
      ? `${Math.round(doctor.mem_avail_kb / 1024)} MB` : '—';
    const uptime = (typeof doctor.uptime_s === 'number') ? this.formatUptime(doctor.uptime_s) : '—';

    return (
      <details className={bad ? 'warn' : ''}>
        <summary>Device health</summary>
        <div>
          Status: <strong className={statusClass}>{statusLabel}</strong>
          {ageSec !== null && (<> — updated {ageSec}s ago</>)}
        </div>
        <dl>
          <dt>Host</dt><dd>{doctor.host || '—'}</dd>
          <dt>Uptime</dt><dd>{uptime}</dd>
          <dt>Temp</dt><dd>{num(doctor.temp_c, ' °C')}</dd>
          <dt>Load (1m)</dt><dd>{typeof doctor.load1 === 'number' ? `${doctor.load1} / 4 cores` : '—'}</dd>
          <dt>Mem available</dt><dd>{memMb !== '—' ? `${memMb} / ~425 MB` : '—'}</dd>
          <dt>Power / thermal</dt>
          <dd><span className={throttled.alert ? 'text-error' : undefined}>{throttled.text}</span></dd>

          <dt>Gateway reachable</dt><dd>{this.boolCell(doctor.gateway_ok)}</dd>
          <dt>Photo provider</dt><dd>{this.boolCell(doctor.photo_ok)}</dd>
          <dt>MQTT broker</dt><dd>{this.boolCell(doctor.mqtt_ok)}</dd>
          <dt>RX wedged (HW fault)</dt><dd>{this.boolCell(doctor.rx_wedged, false)}</dd>

          <dt>Interface</dt><dd>{(doctor.iface || '—')} ({doctor.operstate || '—'})</dd>
          <dt>Carrier / speed</dt>
          <dd>{num(doctor.carrier)}{typeof doctor.speed === 'number' ? ` / ${doctor.speed} Mbit/s` : ''}</dd>
          <dt>RX packets / errors</dt><dd>{num(doctor.rx_packets)} / {num(doctor.rx_errors)}</dd>
          <dt>TX packets / errors</dt><dd>{num(doctor.tx_packets)} / {num(doctor.tx_errors)}</dd>

          <dt>Gateway fails</dt><dd>{num(doctor.gw_fails)}</dd>
          <dt>NIC recoveries</dt><dd>{num(doctor.net_recoveries)}</dd>
          <dt>Last recovery</dt><dd>{doctor.last_recovery_iso || 'never'}</dd>
        </dl>
        <details>
          <summary>Raw doctor payload</summary>
          <pre>{JSON.stringify(doctor, null, 2)}</pre>
        </details>
      </details>
    );
  }

  // [dotted key, value] for everything in the state record that isn't
  // rendered by name. Devices add keys of their own, and those are still
  // shown, generically, rather than dropped.
  static unknownStateKeys(record) {
    // Keys rendered by name, per part; null for a part that isn't an object
    const known = {
      occupancy: ['occupied', 'source', 'distance_cm'],
      slideshow: ['active', 'shown_in', 'night_cover', 'album_filter'],
      screen: ['on', 'since', 'screensaver', 'wanted', 'wanted_reason'],
      errors: null,
      battery: ['level', 'status', 'plugged', 'health', 'technology', 'temperature_c', 'voltage_v'],
      wifi_rssi: null,
      light_lux: null,
      app: ['version', 'version_code', 'started_at', 'device_booted_at'],
      ts: null,
    };
    const out = [];
    Object.entries(record).forEach(([key, val]) => {
      if (!(key in known)) {
        out.push([key, val]);
        return;
      }
      if (!known[key] || !val || typeof val !== 'object' || Array.isArray(val)) return;
      Object.entries(val).forEach(([sub, subVal]) => {
        if (!known[key].includes(sub)) out.push([`${key}.${sub}`, subVal]);
      });
    });
    return out;
  }

  static describeBattery(b) {
    const parts = [];
    if (typeof b.level === 'number') parts.push(`${b.level}%`);
    if (b.status) parts.push(b.status);
    if (b.plugged) parts.push(`plugged into ${b.plugged}`);
    if (b.health) parts.push(`health ${b.health}`);
    if (b.technology) parts.push(b.technology);
    if (typeof b.temperature_c === 'number') parts.push(`${b.temperature_c} °C`);
    if (typeof b.voltage_v === 'number') parts.push(`${b.voltage_v} V`);
    return parts.length ? parts.join(', ') : 'unknown';
  }

  renderDeviceState(record) {
    if (!record) {
      return (
        <details>
          <summary>Device state</summary>
          <p>This device hasn't published a state record.</p>
        </details>
      );
    }
    const num = (v, unit = '') => (typeof v === 'number' ? `${v}${unit}` : '—');
    const ago = (ts) => {
      const secs = Homeboard.secsSince(ts);
      return secs === null ? '—' : this.formatUptime(secs);
    };
    const battery = Homeboard.part(record, 'battery');
    const app = Homeboard.part(record, 'app') || {};
    const version = [app.version, (app.version_code != null) ? `(${app.version_code})` : null]
      .filter((v) => v != null && v !== '').join(' ');
    const unknown = Homeboard.unknownStateKeys(record);
    return (
      <details>
        <summary>Device state</summary>
        <dl>
          {/* A device with no battery reports null, which isn't worth a row */}
          {battery && (<><dt>Battery</dt><dd>{Homeboard.describeBattery(battery)}</dd></>)}
          <dt>Wi-Fi signal</dt><dd>{num(record.wifi_rssi, ' dBm')}</dd>
          <dt>Light</dt><dd>{num(record.light_lux, ' lux')}</dd>
          <dt>App version</dt><dd>{version || '—'}</dd>
          <dt>App uptime</dt><dd>{ago(app.started_at)}</dd>
          <dt>Device uptime</dt><dd>{ago(app.device_booted_at)}</dd>
          {/* ts only moves when something in the record changes, so an old
              one means a quiet device, not a dead one: availability says that */}
          <dt>Last change</dt><dd>{typeof record.ts === 'number' ? `${ago(record.ts)} ago` : '—'}</dd>
          {unknown.map(([key, val]) => (
            <React.Fragment key={key}>
              <dt>{key}</dt>
              <dd>{(val === null || val === undefined) ? '—' : JSON.stringify(val)}</dd>
            </React.Fragment>
          ))}
        </dl>
        <details>
          <summary>Raw state record</summary>
          <pre>{JSON.stringify(record, null, 2)}</pre>
        </details>
      </details>
    );
  }

  // What's wrong with a homeboard, one short line each: the list only flags
  // these, its page has the details. A device without health telemetry (eg a
  // Portal) isn't a problem; telemetry that went stale is.
  static problems(hb) {
    const out = [];
    if (hb.state !== 'online') out.push(`bridge ${hb.state || 'unknown'}`);
    const record = Homeboard.part(hb, 'device_state');
    const errors = record && record.errors;
    if (Array.isArray(errors) && errors.length) {
      out.push(errors.length === 1 ? '1 error' : `${errors.length} errors`);
    }
    if (hb.doctor) {
      const doc = Homeboard.doctorStatus(hb.doctor);
      if (doc.bad) out.push(`health ${doc.label}`);
    }
    const { wanted, mismatch } = Homeboard.screenWanted(Homeboard.part(record, 'screen'));
    if (mismatch) out.push(`screen should be ${wanted}`);
    return out;
  }

  // An empty box of the same size when there's no picture, so the tiles line up
  renderThumb(hb) {
    const url = Homeboard.thumbUrl(hb);
    if (!url) return (<div className="hb-thumb"/>);
    return (<img className="hb-thumb" src={url} alt={`Picture on ${hb.id}`}/>);
  }

  // The list's buttons sit on a clickable tile: a press mustn't also open the page
  renderPrevNext(hb) {
    const cmd = (path) => (e) => {
      e.stopPropagation();
      this.sendCmd(hb.id, path);
    };
    return (
      <div className="hb-actions">
        <button onClick={cmd('prev')}>&#9664; Previous</button>
        <button onClick={cmd('next')}>Next &#9654;</button>
      </div>
    );
  }

  renderRow(hb) {
    const record = Homeboard.part(hb, 'device_state');
    const problems = Homeboard.problems(hb);
    const photo = hb.displayed_photo;
    const summary = photo ? Homeboard.photoSummary(photo) : null;
    const day = summary && Homeboard.photoDay(summary.taken);
    return (
      <div
        key={hb.id}
        className={problems.length ? 'hb-tile hb-bad' : 'hb-tile'}
        onClick={() => { window.location.hash = Homeboard.hbHash(hb.id); }}
      >
        {this.renderThumb(hb)}
        <div>
          <h3 className="hb-name"><a href={Homeboard.hbHash(hb.id)}>{hb.id}</a></h3>
          {problems.length > 0 && (
            <div className="hb-problems">
              {problems.map((p) => (<span key={p} className="hb-problem">{p}</span>))}
            </div>
          )}
          <div className="hb-line">{this.renderOccupancy(Homeboard.part(record, 'occupancy'))}</div>
          {!summary && (<div className="hb-sub"><em>No photo info</em></div>)}
          {summary && summary.album && (<div className="hb-line"><strong>{summary.album}</strong></div>)}
          {summary && (day || summary.location) && (
            <div className="hb-sub">
              {day}
              {day && summary.location && ' · '}
              {summary.location && this.renderLocation(summary.location, summary.mapUrl)}
            </div>
          )}
          {this.renderPrevNext(hb)}
        </div>
      </div>
    );
  }

  renderList() {
    const { homeboards } = this.state;
    return (
      <div>
        <h4 className="dash-heading">{homeboards.length} homeboard(s)</h4>
        <div className="hb-list">
          {homeboards.map((hb) => this.renderRow(hb))}
        </div>
        <details className="hb-settings">
          <summary className="dash-heading">Settings for all homeboards</summary>
          {this.renderAlbumFilter()}
          {this.renderAnnounce()}
        </details>
        <h4 className="dash-heading"><a href="wakeword.html">Wake word recordings</a></h4>
      </div>
    );
  }

  renderDetail(hbId) {
    const back = (<a className="hb-back" href="#">&larr; All homeboards</a>);
    const hb = this.state.homeboards.find((h) => h.id === hbId);
    if (!hb) {
      return (
        <div>
          {back}
          <div className="dash-alert"><b>Unknown homeboard</b><span>{hbId} isn't known (yet?).</span></div>
        </div>
      );
    }
    const online = hb.state === 'online';
    const record = Homeboard.part(hb, 'device_state');
    const slideshow = Homeboard.part(record, 'slideshow');
    return (
      <div>
        {back}
        <div className="hb-panel">
          <h3 className="hb-name">{hb.id}</h3>
          <div className="hb-sub">
            Bridge: <strong className={online ? undefined : 'text-error'}>{hb.state}</strong>
            {online && (<> · Slideshow: <strong>{Homeboard.describeSlideshow(slideshow)}</strong></>)}
          </div>
          <div className="hb-sub">
            Album filter: <em>{Homeboard.describeAlbumFilter(Homeboard.part(slideshow, 'album_filter'), 'unknown')}</em>
          </div>
          {this.renderErrors(record && record.errors)}
          {this.renderControls(hb)}

          <h4 className="dash-heading">Status</h4>
          {this.renderOccupancy(Homeboard.part(record, 'occupancy'))}
          {this.renderScreen(Homeboard.part(record, 'screen'))}

          <h4 className="dash-heading">Now showing</h4>
          <div className="hb-now">
            {this.renderThumb(hb)}
            <div>{this.renderDisplayedPhoto(hb.displayed_photo)}</div>
          </div>

          <h4 className="dash-heading">Device</h4>
          {this.renderDeviceState(record)}
          {this.renderDeviceHealth(hb.doctor)}
        </div>
      </div>
    );
  }

  render() {
    const { homeboards, brokerConnected, loading, selectedId } = this.state;
    if (loading) {
      return (<div>Loading...</div>);
    }
    if (!brokerConnected) {
      return (
        <div>
          <p className="warn">No homeboard broker is reachable.</p>
          <button onClick={this.refresh}>Refresh</button>
        </div>
      );
    }
    if (homeboards.length === 0) {
      return (
        <div>
          <p>No homeboards discovered yet.</p>
          <button onClick={this.refresh}>Refresh</button>
        </div>
      );
    }
    return selectedId ? this.renderDetail(selectedId) : this.renderList();
  }
}

// wakeword.html: the wake word recordings the service kept, for debugging
class HomeboardWakewords extends React.Component {
  static buildProps() {
    return {
      key: 'HomeboardWakewords',
    };
  }

  constructor(props) {
    super(props);
    this.state = { recordings: null };
    this.refresh = this.refresh.bind(this);
    this._poller = null;
  }

  componentDidMount() {
    this.refresh();
    this._poller = mPoll(this.refresh, 10000);
  }

  componentWillUnmount() {
    this._poller?.stop();
  }

  refresh() {
    mJsonGet('/wakeword/ls', (data) => {
      this.setState({ recordings: (data && data.recordings) || [] });
    });
  }

  static describeDuration(r) {
    const parts = [];
    if (typeof r.duration_ms === 'number') parts.push(`${(r.duration_ms / 1000).toFixed(1)} s`);
    if (r.end) parts.push(`ended by ${r.end}`);
    return parts.join(', ');
  }

  // Null until ZmwSpeechToText answers, which it never does when it can't
  // transcribe (eg its model isn't loaded): then it just stays that way
  static renderTranscription(t) {
    if (!t || typeof t !== 'object') return (<em>no transcription</em>);
    const text = (typeof t.text === 'string') ? t.text.trim() : '';
    const c = (t.confidence && typeof t.confidence === 'object') ? t.confidence : {};
    const num = (v) => (typeof v === 'number' ? v.toFixed(2) : null);
    const details = [
      c.language && `${c.language}${num(c.language_prob) ? ` (${num(c.language_prob)})` : ''}`,
      num(c.no_speech_prob) && `no speech ${num(c.no_speech_prob)}`,
      num(c.avg_log_prob) && `avg log prob ${num(c.avg_log_prob)}`,
    ].filter(Boolean);
    return (
      <>
        {text ? text : (<em>nothing understood</em>)}
        {details.length > 0 && (<div className="hb-sub">{details.join(', ')}</div>)}
      </>
    );
  }

  render() {
    const { recordings } = this.state;
    // Relative, so it also works behind the dashboard's proxy prefix
    const back = (<a className="hb-back" href="index.html">&larr; Homeboards</a>);
    if (recordings === null) {
      return (<div>{back}<div>Loading...</div></div>);
    }
    return (
      <div>
        {back}
        <h4 className="dash-heading">{recordings.length} wake word recording(s), newest first</h4>
        {recordings.length === 0 && (<p className="hb-sub">Nothing recorded yet.</p>)}
        {recordings.length > 0 && (
          <table className="plain-table">
            <thead>
              <tr><th>When</th><th>Homeboard</th><th>Recording</th><th>Transcription</th></tr>
            </thead>
            <tbody>
              {recordings.map((r) => (
                <tr key={r.file}>
                  <td>{new Date(r.received * 1000).toLocaleString()}</td>
                  <td>{r.hb_id || (<em>unknown</em>)}</td>
                  <td>
                    <a href={`/wakeword/file/${encodeURIComponent(r.file)}`} download={r.file}>{r.file}</a>
                    <div className="hb-sub">{HomeboardWakewords.describeDuration(r)}</div>
                  </td>
                  <td>{HomeboardWakewords.renderTranscription(r.transcription)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    );
  }
}
