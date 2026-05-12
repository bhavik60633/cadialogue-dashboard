<?php
/**
 * Finance Pipeline — Yoast SEO REST API Field Registration
 *
 * Add this to your WordPress theme's functions.php, or install it as a
 * Must-Use Plugin by saving to: wp-content/mu-plugins/finance-pipeline-yoast.php
 *
 * This is ONLY needed for Yoast SEO users.
 * RankMath users: skip this file entirely.
 *
 * WHY: Yoast does not expose its meta fields via the WordPress REST API by
 * default. This snippet registers them so the Python pipeline can set them
 * when publishing via the REST API.
 */

add_action('init', function () {
    $yoast_fields = [
        '_yoast_wpseo_focuskw',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_title',
        '_yoast_wpseo_canonical',
        '_yoast_wpseo_opengraph-title',
        '_yoast_wpseo_opengraph-description',
        '_yoast_wpseo_twitter-title',
        '_yoast_wpseo_twitter-description',
        '_yoast_wpseo_is_cornerstone',
    ];

    foreach ($yoast_fields as $field) {
        register_post_meta('post', $field, [
            'show_in_rest'  => true,
            'single'        => true,
            'type'          => 'string',
            'auth_callback' => function () {
                return current_user_can('edit_posts');
            },
        ]);
    }
});
