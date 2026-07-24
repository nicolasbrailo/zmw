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
      loading: true,
    };
    this.refresh = this.refresh.bind(this);
    this._timer = null;
  }

  componentDidMount() {
    this.on_app_became_visible();
    this._timer = setInterval(this.refresh, 5000);
  }

  componentWillUnmount() {
    if (this._timer) clearInterval(this._timer);
  }

  on_app_became_visible() {
    this.refresh();
  }

  refresh() {
    mJsonGet('/get_homeboards_state', (data) => {
      const homeboards = (data && data.homeboards) || [];
      this.setState({ homeboards, loading: false });
    }, () => {
      this.setState({ loading: false });
    });
  }

  renderOccupancy(occ) {
    if (!occ) {
      return (<div>Occupancy: <em>unknown</em></div>);
    }
    const state = occ.occupied ? 'Occupied' : 'Empty';
    const distance = (typeof occ.distance_cm === 'number')
      ? `${occ.distance_cm} cm`
      : 'unknown';
    const ago = (typeof occ.ts === 'number')
      ? ` (${Math.max(0, Math.round(Date.now() / 1000 - occ.ts))}s ago)`
      : '';
    return (
      <div>
        Occupancy: <strong>{state}</strong> — distance {distance}{ago}
      </div>
    );
  }

  renderDisplayedPhoto(photo) {
    if (!photo) {
      return (<p>No photo info available.</p>);
    }
    const camera = [photo['Image Make'], photo['Image Model']].filter(Boolean).join(' ');
    const w = photo['EXIF ExifImageWidth'];
    const h = photo['EXIF ExifImageLength'];
    const size = (w && h) ? `${w} x ${h}` : null;
    const taken = photo['EXIF DateTimeOriginal'];
    const geo = photo.reverse_geo || {};
    const location = geo.revgeo || [geo.city, geo.state, geo.country].filter(Boolean).join(', ');
    const gps = photo.gps;
    const mapUrl = (gps && gps.lat != null && gps.lon != null)
      ? `https://www.openstreetmap.org/?mlat=${gps.lat}&mlon=${gps.lon}#map=16/${gps.lat}/${gps.lon}`
      : null;
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
              <dd>
                {mapUrl
                  ? (<a href={mapUrl} target="_blank" rel="noreferrer">{location}</a>)
                  : location}
              </dd>
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
    return (<span style={{ color: good ? 'var(--cemph)' : 'var(--cerror)' }}>{v ? 'yes' : 'no'}</span>);
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
    const tsMs = doctor.ts ? Date.parse(doctor.ts) : NaN;
    const ageSec = Number.isNaN(tsMs) ? null : Math.max(0, Math.round((Date.now() - tsMs) / 1000));
    // No LWT and non-retained: infer liveness from ts. > ~3x the 30s poll = stale.
    const stale = ageSec === null || ageSec > 90;

    const statusLabel = stale ? 'stale / unknown' : (doctor.state || 'unknown');
    let statusColor = 'inherit';
    if (stale || doctor.state === 'net_down') statusColor = 'var(--cerror)';
    else if (doctor.state === 'ok') statusColor = 'var(--cemph)';

    const throttled = this.decodeThrottled(doctor.throttled);
    const memMb = (typeof doctor.mem_avail_kb === 'number')
      ? `${Math.round(doctor.mem_avail_kb / 1024)} MB` : '—';
    const uptime = (typeof doctor.uptime_s === 'number') ? this.formatUptime(doctor.uptime_s) : '—';

    return (
      <details className={(stale || doctor.state === 'net_down' || doctor.state === 'degraded') ? 'warn' : ''}>
        <summary>Device health</summary>
        <div>
          Status: <strong style={{ color: statusColor }}>{statusLabel}</strong>
          {ageSec !== null && (<> — updated {ageSec}s ago</>)}
        </div>
        <dl>
          <dt>Host</dt><dd>{doctor.host || '—'}</dd>
          <dt>Uptime</dt><dd>{uptime}</dd>
          <dt>Temp</dt><dd>{num(doctor.temp_c, ' °C')}</dd>
          <dt>Load (1m)</dt><dd>{typeof doctor.load1 === 'number' ? `${doctor.load1} / 4 cores` : '—'}</dd>
          <dt>Mem available</dt><dd>{memMb !== '—' ? `${memMb} / ~425 MB` : '—'}</dd>
          <dt>Power / thermal</dt>
          <dd><span style={{ color: throttled.alert ? 'var(--cerror)' : 'inherit' }}>{throttled.text}</span></dd>

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

  renderHomeboard(hb) {
    const online = hb.state === 'online';
    const slideshowActive = !!hb.slideshow_active;
    return (
      <div key={hb.id} className={online ? 'card' : 'card warn'}>
        <h3>{hb.id}</h3>
        <div>
          Bridge: <strong>{hb.state}</strong>
          {online && (<> — Slideshow: <strong>{slideshowActive ? 'Active' : 'Not active'}</strong></>)}
        </div>
        {this.renderOccupancy(hb.occupancy)}
        {this.renderDeviceHealth(hb.doctor)}
        {hb.displayed_photo && (
          <>
            <h4>Now showing</h4>
            {this.renderDisplayedPhoto(hb.displayed_photo)}
          </>
        )}
      </div>
    );
  }

  render() {
    const { homeboards, loading } = this.state;
    if (loading) {
      return (<div>Loading...</div>);
    }
    if (homeboards.length === 0) {
      return (
        <div>
          <p>No homeboards discovered yet.</p>
          <button onClick={this.refresh}>Refresh</button>
        </div>
      );
    }
    return (
      <div>
        <div>{homeboards.length} homeboard(s) known</div>
        {homeboards.map((hb) => this.renderHomeboard(hb))}
      </div>
    );
  }
}
