#!/bin/bash
# Updates the dev API IP allowlist with the caller's current IP.
# Usage: ssh root@187.77.217.61 "bash /root/csl-bot/csl-doc-tracker/update_dev_ip.sh ADD <ip>"
#        ssh root@187.77.217.61 "bash /root/csl-bot/csl-doc-tracker/update_dev_ip.sh LIST"

SERVICE=/etc/systemd/system/csl-dashboard.service
ACTION=${1:-LIST}
NEW_IP=$2

current_ips() {
    grep 'CSL_DEV_IPS=' $SERVICE | sed 's/.*CSL_DEV_IPS=//'
}

case $ACTION in
    LIST)
        echo "Current allowed IPs: $(current_ips)"
        ;;
    ADD)
        if [ -z "$NEW_IP" ]; then
            echo "Usage: update_dev_ip.sh ADD <ip>"
            exit 1
        fi
        OLD=$(current_ips)
        if echo "$OLD" | grep -q "$NEW_IP"; then
            echo "IP $NEW_IP already in allowlist"
            exit 0
        fi
        if [ -z "$OLD" ]; then
            NEW="$NEW_IP"
        else
            NEW="$OLD,$NEW_IP"
        fi
        sed -i "s|CSL_DEV_IPS=.*|CSL_DEV_IPS=$NEW|" $SERVICE
        systemctl daemon-reload && systemctl restart csl-dashboard
        echo "Added $NEW_IP — allowlist is now: $NEW"
        ;;
    REMOVE)
        if [ -z "$NEW_IP" ]; then
            echo "Usage: update_dev_ip.sh REMOVE <ip>"
            exit 1
        fi
        OLD=$(current_ips)
        NEW=$(echo "$OLD" | tr ',' '\n' | grep -v "^$NEW_IP$" | paste -sd,)
        sed -i "s|CSL_DEV_IPS=.*|CSL_DEV_IPS=$NEW|" $SERVICE
        systemctl daemon-reload && systemctl restart csl-dashboard
        echo "Removed $NEW_IP — allowlist is now: $NEW"
        ;;
    *)
        echo "Usage: update_dev_ip.sh [LIST|ADD|REMOVE] [ip]"
        ;;
esac
