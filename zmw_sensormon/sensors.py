""" Keeps a historical database of sensor readings """

from apscheduler.triggers.cron import CronTrigger
import sqlite3
import logging
import re
log = logging.getLogger(__name__)

# SQL injection protection: Valid identifier pattern (alphanumeric + underscore, can't start with digit)
_SQL_IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_MAX_IDENTIFIER_LENGTH = 128

# SQLite reserved keywords that should not be used as identifiers
_SQLITE_KEYWORDS = {
    'abort', 'action', 'add', 'after', 'all', 'alter', 'analyze', 'and', 'as', 'asc',
    'attach', 'autoincrement', 'before', 'begin', 'between', 'by', 'cascade', 'case',
    'cast', 'check', 'collate', 'column', 'commit', 'conflict', 'constraint', 'create',
    'cross', 'current_date', 'current_time', 'current_timestamp', 'database', 'default',
    'deferrable', 'deferred', 'delete', 'desc', 'detach', 'distinct', 'drop', 'each',
    'else', 'end', 'escape', 'except', 'exclusive', 'exists', 'explain', 'fail', 'for',
    'foreign', 'from', 'full', 'glob', 'group', 'having', 'if', 'ignore', 'immediate',
    'in', 'index', 'indexed', 'initially', 'inner', 'insert', 'instead', 'intersect',
    'into', 'is', 'isnull', 'join', 'key', 'left', 'like', 'limit', 'match', 'natural',
    'no', 'not', 'notnull', 'null', 'of', 'offset', 'on', 'or', 'order', 'outer', 'plan',
    'pragma', 'primary', 'query', 'raise', 'recursive', 'references', 'regexp', 'reindex',
    'release', 'rename', 'replace', 'restrict', 'right', 'rollback', 'row', 'savepoint',
    'select', 'set', 'table', 'temp', 'temporary', 'then', 'to', 'transaction', 'trigger',
    'union', 'unique', 'update', 'using', 'vacuum', 'values', 'view', 'virtual', 'when',
    'where', 'with', 'without'
}

def _validate_sql_identifier(identifier, identifier_type="identifier"):
    """
    Validates that an identifier (table/column name) is safe to use in SQL queries.

    This prevents SQL injection by ensuring identifiers only contain safe characters.
    Since SQLite doesn't support parameterized table/column names, we must validate them.

    Args:
        identifier: The identifier to validate (table name, column name, etc.)
        identifier_type: Description of what this identifier represents (for error messages)

    Raises:
        ValueError: If the identifier is invalid or potentially unsafe
    """
    if not identifier or not isinstance(identifier, str):
        raise ValueError(f"Invalid {identifier_type}: must be a non-empty string")

    if len(identifier) > _MAX_IDENTIFIER_LENGTH:
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': exceeds maximum length of {_MAX_IDENTIFIER_LENGTH}")

    if not _SQL_IDENTIFIER_PATTERN.match(identifier):
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': must contain only alphanumeric characters "
            f"and underscores, and cannot start with a digit")

    if identifier.lower() in _SQLITE_KEYWORDS:
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': cannot use SQLite reserved keyword")

    return identifier

def sanitize_sql_identifier(name):
    """
    Transforms an arbitrary name (eg 'portaloft-portal') into something that passes
    _validate_sql_identifier (eg 'portaloft_portal'). Invalid chars become underscores,
    a leading digit or reserved keyword gets an underscore added, and the result is
    truncated to the max length. Different names may map to the same identifier.
    """
    ident = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    if not ident or ident[0].isdigit():
        ident = '_' + ident
    if ident.lower() in _SQLITE_KEYWORDS:
        ident = ident + '_'
    return ident[:_MAX_IDENTIFIER_LENGTH]

def _validate_time_unit(unit):
    """Validates time units used in SQLite datetime() function to prevent injection."""
    valid_units = {'years', 'months', 'days', 'hours', 'minutes', 'seconds'}
    if unit not in valid_units:
        raise ValueError(f"Invalid time unit '{unit}': must be one of {valid_units}")
    return unit


def _maybe_create_table(conn, sensor_name, metrics):
    # Validate all identifiers to prevent SQL injection
    sensor_name = _validate_sql_identifier(sensor_name, "sensor name")
    validated_metrics = [_validate_sql_identifier(m, "metric name") for m in metrics]

    metric_cols = ' REAL, '.join(validated_metrics)
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS {sensor_name} ('
        '   sample_time DATETIME DEFAULT CURRENT_TIMESTAMP, '
        f'  {metric_cols} REAL'
        ')')

    # Add any missing columns to existing tables
    _add_missing_columns(conn, sensor_name, validated_metrics)


def _add_missing_columns(conn, sensor_name, metrics):
    """Add any columns that exist in metrics but not in the table."""
    res = conn.execute(f"SELECT name FROM PRAGMA_TABLE_INFO('{sensor_name}')")
    existing_columns = {row[0] for row in res.fetchall()}

    for metric in metrics:
        if metric not in existing_columns:
            log.info("Adding missing column '%s' to table '%s'", metric, sensor_name)
            conn.execute(f'ALTER TABLE {sensor_name} ADD COLUMN {metric} REAL')


def _discard_old_samples_by_retention_count(conn, sensor_name, retention_rows):
    if retention_rows is None or retention_rows <= 0:
        return

    # Validate sensor name to prevent SQL injection
    sensor_name = _validate_sql_identifier(sensor_name, "sensor name")
    retention_rows = int(retention_rows)

    conn.execute(
        f'DELETE FROM {sensor_name} '
        f'WHERE '
        f'  rowid NOT IN ('
        f'    SELECT ROWID FROM {sensor_name} '
        f'    ORDER BY sample_time DESC '
        f'    LIMIT {retention_rows} '
        f'  )'
    )


def _discard_old_samples_by_retention_days(conn, sensor_name, retention_days):
    if retention_days is None:
        return

    # Validate sensor name to prevent SQL injection
    sensor_name = _validate_sql_identifier(sensor_name, "sensor name")
    retention_days = int(retention_days)

    conn.execute(
        f"DELETE FROM {sensor_name} "
        f"WHERE sample_time < datetime('now', '-{retention_days} days')"
    )


def _get_known_sensors(conn):
    res = conn.execute(
        "SELECT name FROM sqlite_schema WHERE type = 'table'").fetchall()
    # unpack, so we return as a vector instead of a vec of tuples
    return [x for (x,) in res]


def _discard_old_samples_by_retention_days_all_tables(conn, retention_days):
    for sensor_name in _get_known_sensors(conn):
        _discard_old_samples_by_retention_days(conn, sensor_name, retention_days)


def _discard_old_samples_by_retention_count_all_tables(conn, retention_days):
    for sensor_name in _get_known_sensors(conn):
        _discard_old_samples_by_retention_count(conn, sensor_name, retention_days)


def _get_sensor_metrics(conn, sensor_name):
    # Validate sensor name to prevent SQL injection
    sensor_name = _validate_sql_identifier(sensor_name, "sensor name")

    res = conn.execute(f"SELECT name FROM PRAGMA_TABLE_INFO('{sensor_name}')")
    # unpack, so we return as a vector instead of a vec of tuples
    # also remove the special metric "sample_time"
    return [metric for (metric,) in res.fetchall() if metric != 'sample_time']


def _get_known_metrics(conn):
    sensors = _get_known_sensors(conn)
    known_metrics = set()
    for s in sensors:
        for m in _get_sensor_metrics(conn, s):
            known_metrics.add(m)
    return known_metrics


def _sensors_with_metric(conn, metric):
    all_sensors = []
    for sensor_name in _get_known_sensors(conn):
        if metric in _get_sensor_metrics(conn, sensor_name):
            all_sensors.append(sensor_name)
    return all_sensors


def _csv(header, data):
    csv = ','.join(header) + '\n'
    for row in data:
        csv += ','.join(str(x) for x in row) + '\n'
    return csv


class SensorsHistory:
    """ Keeps a historical database of sensor readings. This is a pure persistence
    layer - it receives sensor data and stores it, but does not manage callbacks
    or sensor objects directly. """

    def __init__(self, dbpath, scheduler, retention_rows=None, retention_days=None):
        self._retention_rows = retention_rows
        self._retention_days = retention_days
        self._dbpath = dbpath

        # try to open the db once, to verify it's usable
        with sqlite3.connect(self._dbpath):
            pass

        self._scheduler = scheduler

        # Clear old sensors once a day, some time at a random hour during the night
        self._scheduler.add_job(
            self.gc_dead_sensors,
            trigger=CronTrigger(hour=2, minute=22, second=0),
            id='gc_sensor_history'
        )

    def register_to_webserver(self, server):
        """ Will hook this object to a flask-like webserver, so that the sensor
        database is exposed over certain http endpoints """
        server.add_url_rule('/sensors/ls', None, self.get_known_sensors)
        server.add_url_rule('/sensors/metrics', None, self.get_known_metrics)
        server.add_url_rule('/sensors/metrics/<sensor_name>', None, self.get_metrics_for_sensor)
        server.add_url_rule('/sensors/measuring/<metric>', None, self.get_known_sensors_measuring)
        server.add_url_rule('/sensors/get_metric_in_sensor_csv/<sensor_name>/<metric>',
                            None, self.get_metric_in_sensor_csv)
        server.add_url_rule('/sensors/get_metric_in_sensor_csv/<sensor_name>/<metric>/history/<unit>/<time>',
                            None, self.get_metric_in_sensor_csv_time_limit)
        server.add_url_rule('/sensors/get_all_metrics_in_sensor_csv/<sensor_name>',
                            None, self.get_all_metrics_in_sensor_csv)
        server.add_url_rule('/sensors/get_single_metric_in_all_sensors_csv/<metric>',
                            None, self.get_single_metric_in_all_sensors_csv)
        server.add_url_rule('/sensors/get_single_metric_in_all_sensors_csv/<metric>/<unit>/<time>',
                            None, self.get_single_metric_in_all_sensors_csv)
        server.add_url_rule('/sensors/gc_dead_sensors', None, self.gc_dead_sensors)
        ## Only enable this for testing, not a good idea to leave this open
        # server.add_url_rule('/sensors/force_retention_days/<retention_n>', None, self._force_retention_days)
        # server.add_url_rule('/sensors/force_retention_rows/<retention_n>', None, self._force_retention_rows)

    def register_sensor(self, sensor_name, metrics):
        """ Register a sensor schema in the database. Creates the table if needed,
        or adds any missing columns to an existing table. Does not manage callbacks. """
        # Validate sensor name early to catch invalid names at registration
        try:
            _validate_sql_identifier(sensor_name, "sensor name")
        except ValueError as e:
            log.error("Cannot register sensor with invalid name: %s", e)
            raise

        # Validate all metric names early
        for metric in metrics:
            try:
                _validate_sql_identifier(metric, "metric name")
            except ValueError as e:
                log.error("Cannot register sensor %s with invalid metric name: %s", sensor_name, e)
                raise

        with sqlite3.connect(self._dbpath) as conn:
            _maybe_create_table(conn, sensor_name, metrics)
            conn.commit()

        log.info('Registered sensor %s to sensor_history', sensor_name)

    def save_reading(self, sensor_name, values_dict):
        """ Save a sensor reading to the database.

        Args:
            sensor_name: Name of the sensor
            values_dict: Dictionary of {metric_name: value}
        """
        metrics = list(values_dict.keys())
        readings = list(values_dict.values())

        # Validate all identifiers to prevent SQL injection
        sensor_name = _validate_sql_identifier(sensor_name, "sensor name")
        validated_metrics = [_validate_sql_identifier(m, "metric name") for m in metrics]

        with sqlite3.connect(self._dbpath) as conn:
            _maybe_create_table(conn, sensor_name, validated_metrics)

            cols_q = ', '.join(validated_metrics)
            vals_placeholders = ', '.join('?' * len(validated_metrics))
            query = f'INSERT INTO {sensor_name}'\
                    f' ({cols_q}) VALUES ({vals_placeholders})'
            conn.execute(query, readings)

            _discard_old_samples_by_retention_count(
                conn, sensor_name, self._retention_rows)
            _discard_old_samples_by_retention_days(
                conn, sensor_name, self._retention_days)
            conn.commit()

    def get_known_sensors(self):
        """ Returns a list of all sensor names kept in this database """
        with sqlite3.connect(self._dbpath) as conn:
            return _get_known_sensors(conn)

    def get_known_metrics(self):
        """ Returns a list of all metrics being measured """
        with sqlite3.connect(self._dbpath) as conn:
            return list(_get_known_metrics(conn))

    def get_known_sensors_measuring(self, metric):
        """ Returns a list of all sensor that can measure $metric"""
        with sqlite3.connect(self._dbpath) as conn:
            sensors = _get_known_sensors(conn)
            can_measure = []
            for sensor in sensors:
                if metric in _get_sensor_metrics(conn, sensor):
                    can_measure.append(sensor)
            return can_measure

    def get_metrics_for_sensor(self, sensor_name):
        """ Returns a list of all metrics available for a specific sensor """
        with sqlite3.connect(self._dbpath) as conn:
            if sensor_name not in _get_known_sensors(conn):
                return []
            return _get_sensor_metrics(conn, sensor_name)

    def get_metric_in_sensor_csv(self, sensor_name, metric):
        """ Retrieves all measurements of $metric for $sensor """
        return self.get_metric_in_sensor_csv_time_limit(sensor_name, metric, 'days', self._retention_days)

    def get_metric_in_sensor_csv_time_limit(self, sensor_name, metric, unit, time):
        """ Retrieves measurements of $metric for $sensor,
        for samples taken after N units of time (eg 2 days history) """
        # Validate all identifiers to prevent SQL injection
        sensor_name = _validate_sql_identifier(sensor_name, "sensor name")
        metric = _validate_sql_identifier(metric, "metric name")
        unit = _validate_time_unit(unit)
        time = int(time)

        with sqlite3.connect(self._dbpath) as conn:
            if sensor_name not in _get_known_sensors(conn):
                log.error('Received request for unknown sensor %s', sensor_name)
                return ''

            if metric not in _get_sensor_metrics(conn, sensor_name):
                log.error('Received request for unknown metric %s in sensor %s', metric, sensor_name)
                return ''

            query = f"SELECT sample_time, {metric} " +\
                    f"FROM {sensor_name} " +\
                    f"WHERE sample_time > datetime('now', '-{time} {unit}')" +\
                    "ORDER BY sample_time"
            res = conn.execute(query).fetchall()
            return _csv(['sample_time', metric], res)

    def get_all_metrics_in_sensor_csv(self, sensor_name):
        """ Equivalent to select * for a single sensor: retrieves all historical
        data for a single sensor, as far as the retention period allows """
        # Validate sensor name to prevent SQL injection
        sensor_name = _validate_sql_identifier(sensor_name, "sensor name")

        with sqlite3.connect(self._dbpath) as conn:
            if sensor_name not in _get_known_sensors(conn):
                log.error('Received request for unknown sensor %s', sensor_name)
                return ''

            # metrics returned from _get_sensor_metrics are already validated
            metrics = _get_sensor_metrics(conn, sensor_name)
            cols = ','.join(metrics)
            query = f"SELECT sample_time, {cols} FROM {sensor_name} ORDER BY sample_time"
            res = conn.execute(query).fetchall()
            return _csv(['sample_time'] + metrics, res)

    def get_single_metric_in_all_sensors_csv(self, metric, unit='days', time=2):
        """ Gets the same metric, as measured by different sensors. Will check
        on all known sensors (sensors that don't know this metric will be skipped """
        # Validate all parameters to prevent SQL injection
        metric = _validate_sql_identifier(metric, "metric name")
        unit = _validate_time_unit(unit)
        time = int(time)

        with sqlite3.connect(self._dbpath) as conn:
            # all_sensors come from _sensors_with_metric which validates them
            all_sensors = _sensors_with_metric(conn, metric)
            if len(all_sensors) == 0:
                return ''

            # Select a single column per sensor (=table), and enough nulls for all
            # other columns. The query should look like
            # SELECT * FROM (
            #   SELECT metric AS sensor1, NULL as sensor2,   NULL as sensor3...
            #   UNION
            #   SELECT NULL AS sensor1,   metric as sensor2, NULL as sensor3...
            #   UNION
            #   SELECT NULL AS sensor1,   NULL as sensor2,   metric as sensor3...
            #   UNION
            #   ...
            # )
            sensor_qs = []
            for sensor in all_sensors:
                cols_mask = []
                for other_sensor in all_sensors:
                    if other_sensor == sensor:
                        cols_mask.append(f"{metric} AS {sensor}")
                    else:
                        cols_mask.append(f"'' AS {other_sensor}")
                cols = ", ".join(cols_mask)
                sensor_qs.append(f"SELECT sample_time, {cols} "
                                 f"FROM {sensor} "
                                 f"WHERE {metric} IS NOT NULL"
                                 f"  AND sample_time > datetime('now', '-{time} {unit}')")

            query = "SELECT * FROM (" +\
                    (" UNION ".join(sensor_qs)) +\
                    ") ORDER BY sample_time"
            res = conn.execute(query).fetchall()
            return _csv(['sample_time'] + all_sensors, res)

    def gc_dead_sensors(self):
        """Run garbage collection to discard old sensor data based on retention policy."""
        log.info('Sensor history: run GC to discard old sensors')
        with sqlite3.connect(self._dbpath) as conn:
            _discard_old_samples_by_retention_days_all_tables(conn, self._retention_days)
            _discard_old_samples_by_retention_count_all_tables(conn, self._retention_rows)
            conn.commit()
        return "OK"

    def _force_retention_days(self, retention_n):
        retention_n = int(retention_n)
        log.info('Discarding old measurements by forcing DAYS retention to %d', retention_n)
        with sqlite3.connect(self._dbpath) as conn:
            _discard_old_samples_by_retention_days_all_tables(conn, retention_n)
            conn.commit()
        return "OK"

    def _force_retention_rows(self, retention_n):
        retention_n = int(retention_n)
        log.info('Discarding old measurements by forcing ROWS retention to %d', retention_n)
        with sqlite3.connect(self._dbpath) as conn:
            _discard_old_samples_by_retention_count_all_tables(conn, retention_n)
            conn.commit()
        return "OK"
