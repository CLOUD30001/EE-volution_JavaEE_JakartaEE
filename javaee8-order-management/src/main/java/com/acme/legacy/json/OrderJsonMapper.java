package com.acme.legacy.json;

import com.acme.legacy.entity.Order;

import javax.json.bind.Jsonb;
import javax.json.bind.JsonbBuilder;

public class OrderJsonMapper {

    private final Jsonb jsonb = JsonbBuilder.create();

    public String toJson(Order order) {
        return jsonb.toJson(order);
    }

    public Order fromJson(String json) {
        return jsonb.fromJson(json, Order.class);
    }
}
