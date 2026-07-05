#!/usr/bin/env bash
# Provision the probodds_soccer Postgres DB + roles on the target box.
# Credentials are generated on the box and written to /root/probodds_soccer.env (chmod 600).
# Never prints the password.
set -euo pipefail
DB=probodds_soccer

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1; then
  sudo -u postgres createdb "$DB"
  echo "created db $DB"
else
  echo "db $DB already exists"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='soccer_app'" | grep -q 1; then
  PW=$(openssl rand -hex 24)
  sudo -u postgres psql -q -c "CREATE ROLE soccer_app LOGIN PASSWORD '$PW';"
  umask 077
  {
    echo "PGHOST=127.0.0.1"; echo "PGPORT=5432"; echo "PGDATABASE=$DB";
    echo "PGUSER=soccer_app"; echo "PGPASSWORD=$PW";
  } > /root/probodds_soccer.env
  chmod 600 /root/probodds_soccer.env
  echo "created role soccer_app; connection saved to /root/probodds_soccer.env"
else
  echo "role soccer_app already exists"
fi

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='soccer_ro'" | grep -q 1; then
  RPW=$(openssl rand -hex 24)
  sudo -u postgres psql -q -c "CREATE ROLE soccer_ro LOGIN PASSWORD '$RPW';"
  echo "SOCCER_RO_PASSWORD=$RPW" >> /root/probodds_soccer.env
  echo "created read-only role soccer_ro"
fi

sudo -u postgres psql -q -c "ALTER DATABASE $DB OWNER TO soccer_app;"
sudo -u postgres psql -q -c "GRANT ALL ON DATABASE $DB TO soccer_app;"
sudo -u postgres psql -q -d "$DB" -c "GRANT USAGE ON SCHEMA public TO soccer_ro; ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO soccer_ro;"
echo "provision done."
