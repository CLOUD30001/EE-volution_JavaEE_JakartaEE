package com.acme.legacy.util;

import org.apache.commons.lang3.StringUtils;

/**
 * Non-javax dependency, included on purpose as a contrast case: this class
 * needs no javax-&gt;jakarta migration action at all.
 */
public final class StringHelper {

    private StringHelper() {
    }

    public static String normalizeSku(String sku) {
        return StringUtils.trimToEmpty(sku).toUpperCase();
    }
}
