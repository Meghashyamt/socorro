#!/bin/bash
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

#please see README

set -e

CURDIR=$(dirname $0)
VERSION=2.5.1

#echo '*********************************************************'
#echo 'support functions'
#psql -f ${CURDIR}/support_functions.sql breakpad

echo '*********************************************************'
echo 'add dynamic views for daily crash ratios for Metrics'
echo 'bug 733489'
psql -f ${CURDIR}/product_crash_ratio.sql breakpad

echo '*********************************************************'
echo 'drop old unused signatures tables'
echo 'bug 715676'
psql -f ${CURDIR}/drop_old_sig_tables.sql breakpad

#change version in DB
psql -c "SELECT update_socorro_db_version( '$VERSION' )" breakpad

echo "$VERSION upgrade done"

exit 0