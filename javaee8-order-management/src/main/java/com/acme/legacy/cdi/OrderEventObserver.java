package com.acme.legacy.cdi;

import javax.enterprise.context.ApplicationScoped;
import javax.enterprise.event.Observes;

@ApplicationScoped
public class OrderEventObserver {

    public void onOrderPlaced(@Observes OrderPlacedEvent event) {
        System.out.println("Order placed, id=" + event.getOrderId());
    }
}
