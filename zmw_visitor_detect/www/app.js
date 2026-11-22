// Visitor detection UI: why each camera session flagged (or didn't), the discovered visitors, the unknown faces
// waiting to be promoted, and admin actions on them.

const VD_EVENT_LABELS = {
  on_person_detected: 'Person',
  on_face_detected: 'Unknown face',
  on_face_identified: 'Identified',
  on_new_frequent_visitor: 'New visitor',
};

const VD_EVENT_COLORS = {
  on_person_detected: '#1c7ed6',
  on_face_detected: '#868e96',
  on_face_identified: '#2f9e44',
  on_new_frequent_visitor: '#f59f00',
};

function vdTime(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : '-';
}

function vdEventChip(ev, idx) {
  const label = VD_EVENT_LABELS[ev.type] || ev.type;
  return (
    <span key={idx} style={{background: VD_EVENT_COLORS[ev.type] || '#555', color: '#fff', borderRadius: '4px',
                            padding: '1px 6px', marginRight: '4px', fontSize: '0.85em', whiteSpace: 'nowrap'}}>
      {label}{ev.name ? `: ${ev.name}` : ''}{ev.t != null ? ` @${Math.round(ev.t)}s` : ''}
    </span>
  );
}

// Timeline of one session: person checks (ran / skipped), faces (gated / rejected) and the events published on
// MQTT. Full width; positions are percentages of the session's duration. Hovering (or clicking) an event shows the
// MQTT message as it was published.
function VdTimeline(props) {
  const log = props.log;
  const [sel, setSel] = React.useState(null);
  const dur = Math.max(log.analysed_s || 1, 1);
  const H = 72;
  const x = (t) => `${0.5 + 99 * Math.min(t, dur) / dur}%`;
  const marks = [];
  log.person_checks.forEach((c, i) => {
    const hit = c.ran ? c.persons.length > 0 : c.persons_reused > 0;
    marks.push(<rect key={`p${i}`} x={x(c.t)} y={6} width={5} height={14} transform="translate(-2.5, 0)"
                     fill={hit ? '#1c7ed6' : (c.ran ? '#666' : 'none')} stroke="#1c7ed6" strokeWidth={c.ran ? 0 : 1}>
                 <title>{`t=${c.t}s person check ${c.ran ? 'ran' : 'skipped (no motion)'}: ` +
                         (c.ran ? c.persons.map(p => p.conf).join(', ') || 'nobody' : `${c.persons_reused} reused`) +
                         ((c.too_small || []).length ? `; ignored ${c.too_small.length} too small (far away)` : '')}</title>
               </rect>);
  });
  log.faces.forEach((f, i) => {
    marks.push(<circle key={`f${i}`} cx={x(f.t)} cy={32} r={3}
                       fill={f.gate === 'ok' ? '#e8590c' : (f.gate.startsWith('ok') ? '#f5a97f' : '#888')}>
                 <title>{`t=${f.t}s track ${f.track} conf ${f.conf} iod ${f.iod}px yaw ${f.yaw}: ${f.gate}` +
                         (f.split ? ' (split into a new track)' : '')}</title>
               </circle>);
  });
  log.events.forEach((e, i) => {
    const color = VD_EVENT_COLORS[e.type] || '#f59f00';
    marks.push(
      <g key={`e${i}`} style={{cursor: 'pointer'}} onMouseEnter={() => setSel(i)} onClick={() => setSel(i)}>
        {/* Wide transparent line: an easier target to hover than the 3px marker */}
        <line x1={x(e.t)} x2={x(e.t)} y1={40} y2={H - 4} stroke="transparent" strokeWidth={14} />
        <line x1={x(e.t)} x2={x(e.t)} y1={42} y2={H - 6} stroke={color} strokeWidth={sel === i ? 5 : 3} />
      </g>);
  });
  // The message as published: the log adds 'type' (the same as 'event') for the UI
  const message = (e) => {
    const { type, ...msg } = e;
    return JSON.stringify(msg, null, 2);
  };
  const ev = sel != null ? log.events[sel] : null;
  return (
    <div>
      <svg width="100%" height={H} style={{display: 'block'}}>
        <rect x={0} y={0} width="100%" height={H} fill="none" stroke="#444" />
        {marks}
        <text x="99.5%" y={H - 4} fill="#888" fontSize="10" textAnchor="end">{`${dur}s`}</text>
      </svg>
      {log.events.length > 0 && (ev ? (
        <div>
          <b>MQTT {ev.event}</b> at {ev.t}s {ev.track_id != null && <small>(track {ev.track_id})</small>}
          <pre style={{whiteSpace: 'pre-wrap', fontSize: '0.85em', margin: '2px 0'}}>{message(ev)}</pre>
        </div>
      ) : <small>Hover or click an event line to see the MQTT message it published.</small>)}
    </div>
  );
}

// People in a session, each with the tracks (continuous sightings of a face) that were linked to them. A person
// starts at a track that was reported (unknown or identified); later tracks that matched it are "same person".
function VdPeople(props) {
  const { tracks, img } = props;
  const byId = {};
  tracks.forEach(tr => { byId[tr.id] = tr; });
  const people = [];
  const rootOf = {};
  let letter = 0;
  tracks.forEach(tr => {
    const kind = tr.decision ? tr.decision.kind : null;
    if (kind === 'unknown' || kind === 'identified') {
      const label = kind === 'identified' ? `${tr.decision.who} (identified, ${tr.decision.sim})`
                                          : `Person ${String.fromCharCode(65 + letter++)} (unknown)`;
      rootOf[tr.id] = { label, tracks: [tr] };
      people.push(rootOf[tr.id]);
    }
  });
  const undecided = [], faceless = [];
  tracks.forEach(tr => {
    if (tr.same_as != null && rootOf[tr.same_as]) rootOf[tr.same_as].tracks.push(tr);
    else if (!tr.decision) (tr.gated ? undecided : faceless).push(tr);
  });
  const rows = people.concat(
    undecided.length ? [{ label: 'Undecided (fewer than 2 good faces)', tracks: undecided }] : [],
    faceless.length ? [{ label: 'No usable face', tracks: faceless }] : []);
  if (!rows.length) return null;
  const cell = tr => (
    <span key={tr.id} style={{display: 'inline-block', textAlign: 'center', marginRight: '6px', verticalAlign: 'top'}}>
      {/* Logs from before track photos existed only have the best faces of tracks with good faces */}
      {img(tr.photo || (tr.best && tr.best.length ? tr.best[0].ctx : null), '70px') ||
       <div title="no photo: no usable face (or a log from before track photos)"
            style={{height: '70px', width: '70px', background: '#333'}} />}
      <br/><small>track {tr.id} · {tr.first_t}-{tr.last_t}s<br/>
        {tr.gated}/{tr.seen} good{tr.same_as != null ? ` · sim ${tr.decision.sim}` : ''}</small>
    </span>
  );
  return (
    <table>
      <thead><tr><th>Person</th><th>Tracks (photo: first good face, else first face seen)</th></tr></thead>
      <tbody>
        {rows.map((p, i) => <tr key={i}><td>{p.label}</td><td>{p.tracks.map(cell)}</td></tr>)}
      </tbody>
    </table>
  );
}

class VdSessionDetail extends React.Component {
  constructor(props) {
    super(props);
    this.state = { log: null, error: null };
  }

  componentDidMount() {
    mJsonGet(`${this.props.api}/session/${this.props.sessionId}`,
             (log) => this.setState({ log }),
             () => this.setState({ error: 'No decision log (still running, or pruned)' }));
  }

  render() {
    const { log, error } = this.state;
    if (error) return <p>{error}</p>;
    if (!log) return <p>Loading...</p>;
    const img = (rel, h) => rel ? <img src={`${this.props.api}/data/${rel}`} style={{height: h || '80px', marginRight: '2px'}}
                                       onClick={() => this.props.onZoom(`${this.props.api}/data/${rel}`)} /> : null;
    const gateCounts = {};
    log.faces.forEach(f => { const k = f.gate.split(' (')[0]; gateCounts[k] = (gateCounts[k] || 0) + 1; });
    const st = log.stats || {};
    return (
      <div className="card">
        {log.tracks.length > 0 && <VdPeople tracks={log.tracks} img={img} />}
        <VdTimeline log={log} />
        <small>Blue bars: person checks (filled = person found, hollow = skipped, no motion). Dots: faces (orange =
          passed the quality gate). Lines: MQTT events published; hover one to see its message.</small>
        <p>
          Stopped: <b>{log.stop_reason}</b> after {log.analysed_s}s of video ({Object.values(log.timing || {}).reduce((a, b) => a + b, 0).toFixed(1)}s
          of compute, mode {log.mode},
          trigger {log.trigger}). Frames {st.frames || 0}: person checks {st.person_runs || 0} ran /
          {' '}{st.person_skipped_still || 0} skipped, {st.persons_too_small || 0} people ignored as too small
          (far away); face detector {st.scrfd_runs || 0} ran,
          {' '}{st.skipped_still || 0} skipped (no motion), {st.skipped_night || 0} skipped (night);
          {' '}{log.dropped_frames || 0} frames dropped (busy).
          {log.inference && <> Models on the {log.inference.toUpperCase()}.</>}
          {log.stream && <> Decoded on the {(log.stream.decoder || 'cpu').toUpperCase()}
            {log.stream.decode_cpu_s !== undefined && ` (${log.stream.decode_cpu_s}s of CPU)`}. First frame
            {' '}{log.stream.event_to_first_frame_s}s after the camera event
            (ffmpeg {log.stream.ffmpeg_to_first_frame_s}s), analysis up to {log.stream.max_lag_s}s behind.</>}
        </p>
        <p>
          Faces seen: {log.faces.length}. Quality gate: {Object.entries(gateCounts).map(([k, v]) => `${k} ${v}`).join(', ') || 'no faces'}.
        </p>
        {log.person_crop && <div>First person: {img(log.person_crop, '120px')}</div>}
        {log.tracks.length > 0 && (
          <table>
            <thead><tr><th>Track</th><th>Faces</th><th>Rejected</th><th>Decision</th><th>Best faces</th></tr></thead>
            <tbody>
              {log.tracks.map(tr => (
                <tr key={tr.id}>
                  <td>{tr.id}<br/><small>{tr.first_t}-{tr.last_t}s</small></td>
                  <td>{tr.gated} gated / {tr.seen} seen</td>
                  <td><small>{Object.entries(tr.rejects).map(([k, v]) => `${k} ${v}`).join(', ') || '-'}</small></td>
                  <td>{tr.decision ? `${tr.decision.kind}${tr.decision.who ? ' ' + tr.decision.who : ''} (${tr.decision.sim})`
                                   : (tr.gated ? 'undecided (needs more gated faces)' : 'no usable face')}
                      {tr.stored && <small><br/>stored</small>}</td>
                  <td>{tr.best.map((b, i) => <span key={i}>{img(b.ctx)}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(log.discovery || []).length > 0 && (
          <p>After this session, discovery promoted: {log.discovery.map(d => `${d.name} (${d.visits} visits, ${d.days} days)`).join(', ')}</p>
        )}
      </div>
    );
  }
}

class VdSessions extends React.Component {
  constructor(props) {
    super(props);
    this.state = { filter: 'all', open: null };
  }

  matches(s) {
    const evs = s.summary ? s.summary.events : [];
    switch (this.state.filter) {
      case 'flagged': return evs.length > 0;
      case 'quiet': return s.summary && evs.length === 0;
      case 'faces': return evs.some(e => e.type !== 'on_person_detected');
      case 'day': return s.summary && s.summary.mode !== 'night';
      case 'night': return s.summary && s.summary.mode === 'night';
      default: return true;
    }
  }

  render() {
    const sessions = (this.props.sessions || []).filter(s => this.matches(s));
    return (
      <div>
        Show: <select value={this.state.filter} onChange={e => this.setState({ filter: e.target.value })}>
          <option value="all">all</option>
          <option value="flagged">flagged</option>
          <option value="faces">with faces</option>
          <option value="quiet">nothing fired</option>
          <option value="day">day</option>
          <option value="night">night</option>
        </select>
        <small> {sessions.length} sessions. Click one to see why it flagged (or didn't).</small>
        <table>
          <thead><tr><th>When</th><th>Person</th><th>Events</th><th>Why it stopped</th></tr></thead>
          <tbody>
            {sessions.map(s => [
              <tr key={s.id} style={{cursor: 'pointer'}}
                  onClick={() => this.setState({ open: this.state.open === s.id ? null : s.id })}>
                <td>{vdTime(s.start_ts)}<br/><small>{s.cam_alias} · {s.summary ? `${s.summary.mode} · ${s.summary.trigger}` : 'running'}</small></td>
                <td>{s.summary?.person_crop && s.has_log &&
                     <img src={`${this.props.api}/data/${s.summary.person_crop}`} style={{height: '60px'}} />}</td>
                <td>{s.summary ? (s.summary.events.length ? s.summary.events.map(vdEventChip) : <small>nothing</small>) : '...'}</td>
                <td><small>{s.summary ? `${s.summary.stop_reason}, ${Math.round(s.summary.analysed_s)}s analysed` : ''}</small></td>
              </tr>,
              this.state.open === s.id && (
                <tr key={`${s.id}_detail`}><td colSpan={4}>
                  {s.has_log ? <VdSessionDetail api={this.props.api} sessionId={s.id} onZoom={this.props.onZoom} />
                             : <small>No decision log (still running, or pruned)</small>}
                </td></tr>
              ),
            ])}
          </tbody>
        </table>
      </div>
    );
  }
}

class VdVisitors extends React.Component {
  constructor(props) {
    super(props);
    this.state = { open: null };
  }

  admin(op, payload, confirmMsg) {
    if (confirmMsg && !window.confirm(confirmMsg)) return;
    mJsonPut(`${this.props.api}/admin/${op}`, payload, () => this.props.onChanged());
  }

  split(v) {
    const thr = window.prompt(`Split ${v.name}: re-cluster its faces at a stricter similarity (merging threshold ` +
                              `is ${this.props.config.same_person_thr}). Threshold:`, '0.55');
    if (thr) this.admin('split_identity', { id: v.id, thr: parseFloat(thr) });
  }

  merge(v, others) {
    const into = window.prompt(`Merge ${v.name} into which visitor id? (${others.map(o => `${o.id}: ${o.name}`).join(', ')})`);
    if (into) this.admin('merge_identities', { keep_id: parseInt(into), other_id: v.id });
  }

  render() {
    const visitors = this.props.visitors || [];
    if (visitors.length === 0) {
      return <p>No visitors discovered yet. A face seen in {this.props.config.discovery_min_visits} visits on
        {' '}{this.props.config.discovery_min_days} different days becomes a visitor (see the Unknown faces tab).</p>;
    }
    return (
      <div>
        <p><small>Name a visitor with <code>"visitor_names": {'{'}"visitor_3": "Name"{'}'}</code> in the service
          config.</small></p>
        {visitors.map(v => (
          <div key={v.id} className="card">
            <b>{v.name}</b> <small>({v.key}{v.named ? '' : ', unnamed'})</small><br/>
            <small>{v.visits} visits on {v.days} days, {v.tracks.length} sightings, gallery {v.gallery_size}.
              First seen {vdTime(v.first_seen)}, last seen {vdTime(v.last_seen)}.</small>
            <div>
              {v.tracks.slice(0, this.state.open === v.id ? v.tracks.length : 8).map(tr => (
                <span key={tr.row} style={{display: 'inline-block', textAlign: 'center', marginRight: '4px'}}>
                  {tr.best[0] && <img src={`${this.props.api}/data/${tr.best[0].ctx || tr.best[0].crop}`}
                                      style={{height: '80px'}} title={`${tr.session_id} track ${tr.track_id} sim ${tr.sim || '-'}`}
                                      onClick={() => this.props.onZoom(`${this.props.api}/data/${tr.best[0].ctx || tr.best[0].crop}`)} />}
                  {this.state.open === v.id && <><br/><button onClick={() => this.admin('remove_track', { track_row: tr.row },
                      'Remove this face from the visitor? (it is dropped, not returned to the unknown pool)')}>Not them</button></>}
                </span>
              ))}
            </div>
            <button onClick={() => this.setState({ open: this.state.open === v.id ? null : v.id })}>
              {this.state.open === v.id ? 'Less' : 'All faces / fix'}</button>
            <button onClick={() => this.split(v)}>Split</button>
            <button onClick={() => this.merge(v, visitors.filter(o => o.id !== v.id))}>Merge into...</button>
            <button onClick={() => this.admin('delete_identity', { id: v.id, to_pool: true },
                `Delete ${v.name}? Its faces go back to the unknown pool and may be rediscovered as a new visitor.`)}>
              Delete (keep faces)</button>
            <button onClick={() => this.admin('delete_identity', { id: v.id, to_pool: false },
                `Delete ${v.name} and all its faces? This can't be undone.`)}>Delete (forget)</button>
          </div>
        ))}
      </div>
    );
  }
}

class VdUnknown extends React.Component {
  render() {
    const clusters = this.props.clusters || [];
    if (clusters.length === 0) return <p>No unknown faces waiting.</p>;
    return (
      <div>
        <p><small>Unknown faces grouped by similarity, the same way discovery does. A group seen in enough visits
          on enough days becomes a visitor. Faces expire after {this.props.config.unknown_ttl_days} days.</small></p>
        {clusters.map((c, i) => (
          <div key={i} className="card">
            <small>{c.tracks.length} sightings · visits {c.visits}/{c.needs_visits} · days {c.days}/{c.needs_days}</small>
            <div>
              {c.tracks.map(tr => tr.best[0] && (
                <img key={tr.row} src={`${this.props.api}/data/${tr.best[0].ctx || tr.best[0].crop}`}
                     style={{height: '80px', marginRight: '2px'}} title={`${tr.session_id} track ${tr.track_id}`}
                     onClick={() => this.props.onZoom(`${this.props.api}/data/${tr.best[0].ctx || tr.best[0].crop}`)} />
              ))}
            </div>
            <button onClick={() => {
              if (!window.confirm('Forget these faces? They will not count towards discovering a visitor.')) return;
              mJsonPut(`${this.props.api}/admin/reset_tracks`, { track_rows: c.track_rows }, () => this.props.onChanged());
            }}>Reset this group</button>
          </div>
        ))}
      </div>
    );
  }
}

// Plays a clip on the server as if it were a camera's live stream: a real session, with events and learning
class VdInject extends React.Component {
  constructor(props) {
    super(props);
    this.state = { cam: props.cams[0] || '', path: '', result: null };
  }

  inject() {
    this.setState({ result: 'Starting...' });
    mJsonPut(`${this.props.api}/inject_clip`, { cam_alias: this.state.cam, path: this.state.path },
             (r) => this.setState({ result: `Started session ${r.session_id}; it shows in Active sessions` }),
             () => this.setState({ result: null }));
  }

  render() {
    return (
      <div>
        <h3>Inject a clip</h3>
        <p><small>Plays a recorded clip on the server through the pipeline, in real time, as if it were the camera.
          It fires events and feeds the identity store like a real visit.</small></p>
        <select value={this.state.cam} onChange={(e) => this.setState({ cam: e.target.value })}>
          {this.props.cams.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <input type="text" size="60" placeholder="/absolute/path/to/clip.mp4" value={this.state.path}
               onChange={(e) => this.setState({ path: e.target.value })} />
        <button disabled={!this.state.path} onClick={() => this.inject()}>Inject</button>
        {this.state.result && <p>{this.state.result}</p>}
      </div>
    );
  }
}

function VdStatus(props) {
  const s = props.status;
  if (!s) return <p>Loading...</p>;
  return (
    <div>
      {s.alerts.length > 0 && <div className="card warn">{s.alerts.map((a, i) => <div key={i}>{a}</div>)}</div>}
      {s.models_missing.length > 0 && <p>Missing models: {s.models_missing.join(', ')} (run make download_models)</p>}
      <p>Models: <b>{s.inference || 'not loaded'}</b></p>
      {s.decoding && (
        <p>Video decoding: <b>{s.decoding.decoder === 'gpu' ? `GPU (VA-API, ${s.decoding.device})` : 'CPU'}</b>
          {s.decoding.decoder === 'cpu' && s.decoding.reason && <small> ({s.decoding.reason})</small>}</p>
      )}
      <h3>Active sessions</h3>
      {s.active_sessions.length === 0 ? <p>None</p> : (
        <table>
          <thead><tr><th>Session</th><th>Stream time</th><th>Compute</th><th>Frames</th><th>Dropped</th><th>Events</th></tr></thead>
          <tbody>
            {s.active_sessions.map(a => (
              <tr key={a.session_id}>
                <td>{a.session_id}<br/><small>{a.trigger}</small></td><td>{a.t}s</td><td>{a.compute_s}s</td>
                <td>{a.frames}</td><td>{a.dropped}</td><td>{a.events.join(', ') || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <VdInject api={props.api} cams={s.config.cam_aliases || []} />
      <h3>Config in use</h3>
      <pre style={{whiteSpace: 'pre-wrap'}}>{JSON.stringify(s.config, null, 1)}</pre>
    </div>
  );
}

class VisitorDetect extends React.Component {
  static buildProps(api_base_path = '', https_server = '') {
    return { key: 'visitor_detect', api_base_path, https_server };
  }

  constructor(props) {
    super(props);
    // Other services link to a session with #session=<id> (eg ZmwDoorman's history)
    const linked = /(?:^#|&)session=([\w-]+)/.exec(window.location.hash);
    this.state = { tab: 'sessions', sessions: null, visitors: null, clusters: null, status: null, zoom: null,
                   linkedSession: linked ? linked[1] : null };
    this.refresh = this.refresh.bind(this);
  }

  componentDidMount() {
    this.refresh();
    this.poller = mPoll(this.refresh, 10000);
  }

  componentWillUnmount() {
    this.poller?.stop();
  }

  refresh() {
    const api = this.props.api_base_path;
    // Status carries the config the other tabs use for their explanations
    mJsonGet(`${api}/status`, (status) => this.setState({ status }));
    switch (this.state.tab) {
      case 'sessions': mJsonGet(`${api}/sessions?limit=200`, (sessions) => this.setState({ sessions })); break;
      case 'visitors': mJsonGet(`${api}/visitors`, (visitors) => this.setState({ visitors })); break;
      case 'unknown': mJsonGet(`${api}/unknown`, (clusters) => this.setState({ clusters })); break;
      default: break;
    }
  }

  setTab(tab) {
    this.setState({ tab }, this.refresh);
  }

  render() {
    const api = this.props.api_base_path;
    const config = this.state.status ? this.state.status.config : {};
    const zoom = (url) => this.setState({ zoom: url });
    const tabs = [['sessions', 'Sessions'], ['visitors', 'Visitors'], ['unknown', 'Unknown faces'], ['status', 'Status']];
    return (
      <div>
        {this.state.zoom && (
          <dialog open onClick={() => this.setState({ zoom: null })}>
            <img src={this.state.zoom} style={{maxWidth: '90vw', maxHeight: '90vh'}} />
          </dialog>
        )}
        <div>
          {tabs.map(([k, label]) => (
            <button key={k} disabled={this.state.tab === k} onClick={() => this.setTab(k)}>{label}</button>
          ))}
          {this.state.status && this.state.status.alerts.length > 0 && <span className="warn"> ⚠ see Status</span>}
        </div>
        {this.state.tab === 'sessions' && this.state.linkedSession && (
          <div>
            <h3>Session {this.state.linkedSession}
              <button onClick={() => {
                history.replaceState(null, '', window.location.pathname + window.location.search);
                this.setState({ linkedSession: null });
              }}>Close</button>
            </h3>
            <VdSessionDetail api={api} sessionId={this.state.linkedSession} onZoom={zoom} />
          </div>
        )}
        {this.state.tab === 'sessions' && <VdSessions api={api} sessions={this.state.sessions} onZoom={zoom} />}
        {this.state.tab === 'visitors' && <VdVisitors api={api} visitors={this.state.visitors} config={config}
                                                       onZoom={zoom} onChanged={this.refresh} />}
        {this.state.tab === 'unknown' && <VdUnknown api={api} clusters={this.state.clusters} config={config}
                                                     onZoom={zoom} onChanged={this.refresh} />}
        {this.state.tab === 'status' && <VdStatus api={api} status={this.state.status} />}
      </div>
    );
  }
}
