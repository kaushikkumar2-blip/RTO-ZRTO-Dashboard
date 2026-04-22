-- RTO / ZRTO extract for the dashboard.
-- {end_date} is substituted at runtime with (today - 15 days) in YYYYMMDD.

WITH total_shipments AS (
    SELECT
        shipment_received_at_origin_date_key AS reporting_date,
        seller_type,
        CASE
            WHEN LOWER(payment_type) = 'prepaid' THEN 'prepaid'
            ELSE 'cod'
        END AS payment_type,
        COUNT(DISTINCT vendor_tracking_id) AS total_shipment_count
    FROM
        bigfoot_external_neo.scp_fsgde_ns__externalisation_l1_scala_fact
    WHERE
        seller_type NOT IN (
            'Non-FA','FA','WSR','MYN','MYS','FKW','FKH','MYE',
            'MP_FBF_SELLER','MP_NON_FBF_SELLER',
            'SF2','SF4','SF6','SF7','FMP','FKMP')
        AND shipment_received_at_origin_date_key BETWEEN 20220101 AND {end_date}
    GROUP BY 1, 2, 3
),

rto_classified AS (
    SELECT
        t.shipment_received_at_origin_date_key AS reporting_date,
        t.seller_type,
        t.seller_id,
        CASE
            WHEN LOWER(t.payment_type) = 'prepaid' THEN 'prepaid'
            ELSE 'cod'
        END AS payment_type,
        t.vendor_tracking_id,
        t.last_undelivery_status,
        t.first_undelivery_status,

        CASE
            WHEN t.shipment_received_at_origin_date_key IS NULL THEN 'Non_ZRTO'
            WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) = 0
                 AND t.first_undelivery_status IN (
                     'Undelivered_Order_Rejected_By_Customer',
                     'Undelivered_No_Response',
                     'Undelivered_HeavyLoad',
                     'Undelivered_Heavy_Rain',
                     'Undelivered_Security_Instability'
                 ) THEN 'Non_ZRTO'
            WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) = 0
                 AND COALESCE(t.first_undelivery_status, '') NOT IN (
                     'Undelivered_Order_Rejected_By_Customer',
                     'Undelivered_No_Response',
                     'Undelivered_HeavyLoad',
                     'Undelivered_Heavy_Rain',
                     'Undelivered_Security_Instability'
                 )
                 AND t.last_undelivery_status IN (
                     'Undelivered_Order_Rejected_By_Customer',
                     'Undelivered_No_Response',
                     'Undelivered_HeavyLoad',
                     'Undelivered_Heavy_Rain',
                     'Undelivered_Security_Instability'
                 ) THEN 'Non_ZRTO'
            WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) > 0 THEN 'Non_ZRTO'
            ELSE 'ZRTO'
        END AS rto_type,

        CASE
            WHEN t.shipment_received_at_origin_date_key IS NULL
                 OR COALESCE(t.fsd_number_of_ofd_attempts, 0) > 0
                 OR (COALESCE(t.fsd_number_of_ofd_attempts, 0) = 0
                     AND (t.first_undelivery_status IN (
                              'Undelivered_Order_Rejected_By_Customer',
                              'Undelivered_No_Response',
                              'Undelivered_HeavyLoad',
                              'Undelivered_Heavy_Rain',
                              'Undelivered_Security_Instability')
                          OR t.last_undelivery_status IN (
                              'Undelivered_Order_Rejected_By_Customer',
                              'Undelivered_No_Response',
                              'Undelivered_HeavyLoad',
                              'Undelivered_Heavy_Rain',
                              'Undelivered_Security_Instability')))
            THEN
                CASE
                    WHEN COALESCE(t.upstream_triggered_rto, FALSE) = TRUE
                    THEN 'Cancelled_by_Client'

                    WHEN t.last_undelivery_status = 'Undelivered_Order_Rejected_By_Customer'
                    THEN 'ORC'

                    WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) >= 3
                         AND t.last_undelivery_status = 'Undelivered_No_Response'
                    THEN 'Attempt_GTE3_CNR'

                    WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) >= 3
                         AND t.last_undelivery_status = 'Undelivered_Request_For_Reschedule'
                    THEN 'Attempt_GTE3_RFR'

                    WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) >= 3
                    THEN 'Attempt_GTE3_Other'

                    WHEN COALESCE(t.fsd_number_of_ofd_attempts, 0) IN (1, 2)
                    THEN 'Attempt_1_or_2'

                    ELSE 'Non_ZRTO_Others'
                END

            WHEN t.last_undelivery_status = 'Undelivered_NonServiceablePincode'
                THEN 'ZRTO_NSS'
            WHEN t.last_undelivery_status = 'Undelivered_Shipment_Damage'
                THEN 'ZRTO_Damage'
            WHEN t.last_undelivery_status = 'Undelivered_SameStateMisroute'
                THEN 'ZRTO_SSM'
            WHEN t.last_undelivery_status = 'Undelivered_OtherStateMisroute'
                THEN 'ZRTO_OSM'
            WHEN t.last_undelivery_status = 'Undelivered_Request_For_Reschedule'
                 AND t.first_undelivery_status = 'Undelivered_SameStateMisroute'
                THEN 'ZRTO_SSM'
            WHEN t.last_undelivery_status = 'Undelivered_Request_For_Reschedule'
                 AND t.first_undelivery_status = 'Undelivered_Shipment_Damage'
                THEN 'ZRTO_Damage'
            WHEN t.last_undelivery_status = 'Undelivered_Request_For_Reschedule'
                 AND t.first_undelivery_status = 'Undelivered_NonServiceablePincode'
                THEN 'ZRTO_NSS'
            WHEN t.last_undelivery_status = 'Undelivered_Request_For_Reschedule'
                 AND t.first_undelivery_status = 'Undelivered_OtherStateMisroute'
                THEN 'ZRTO_OSM'
            WHEN t.first_undelivery_status = 'Undelivered_NonServiceablePincode'
                THEN 'ZRTO_NSS'
            WHEN t.first_undelivery_status = 'Undelivered_Shipment_Damage'
                THEN 'ZRTO_Damage'
            WHEN t.first_undelivery_status = 'Undelivered_SameStateMisroute'
                THEN 'ZRTO_SSM'
            WHEN t.first_undelivery_status = 'Undelivered_OtherStateMisroute'
                THEN 'ZRTO_OSM'
            ELSE 'ZRTO_others'
        END AS rto_reason,

        CASE
            WHEN t.shipped_lpd_date_key >= t.rto_create_date_key
                THEN 'RTO On/Before LPD'
            ELSE 'Breach'
        END AS LPD_Bucket

    FROM
        bigfoot_external_neo.scp_fsgde_ns__externalisation_l1_scala_fact t
    WHERE
        t.seller_type NOT IN (
            'Non-FA','FA','WSR','MYN','MYS','FKW','FKH','MYE',
            'MP_FBF_SELLER','MP_NON_FBF_SELLER',
            'SF2','SF4','SF6','SF7','FMP','FKMP')
        AND LOWER(t.ekl_shipment_type) = 'approved_rto'
        AND t.shipment_received_at_origin_date_key BETWEEN 20220101 AND {end_date}
)

SELECT
    r.reporting_date,
    r.seller_type,
    r.payment_type,
    r.rto_type,
    r.rto_reason,
    r.last_undelivery_status,
    r.LPD_Bucket,
    COUNT(DISTINCT r.vendor_tracking_id) AS rto_count,
    ts.total_shipment_count
FROM
    rto_classified r
LEFT JOIN
    total_shipments ts
    ON r.reporting_date = ts.reporting_date
    AND r.seller_type = ts.seller_type
    AND r.payment_type = ts.payment_type
GROUP BY
    1, 2, 3, 4, 5, 6, 7, 9
ORDER BY
    reporting_date, seller_type, rto_count DESC;
