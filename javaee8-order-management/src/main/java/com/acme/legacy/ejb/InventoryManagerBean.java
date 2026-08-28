package com.acme.legacy.ejb;

import javax.annotation.PostConstruct;
import javax.ejb.Lock;
import javax.ejb.LockType;
import javax.ejb.Singleton;
import javax.ejb.Startup;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Singleton
@Startup
public class InventoryManagerBean {

    private final Map<String, Integer> stockLevels = new ConcurrentHashMap<>();

    @PostConstruct
    public void init() {
        stockLevels.put("ACM-1001", 500);
        stockLevels.put("ACM-1002", 250);
    }

    @Lock(LockType.READ)
    public int getStock(String sku) {
        return stockLevels.getOrDefault(sku, 0);
    }

    @Lock(LockType.WRITE)
    public void reserve(String sku, int quantity) {
        stockLevels.merge(sku, -quantity, Integer::sum);
    }
}
