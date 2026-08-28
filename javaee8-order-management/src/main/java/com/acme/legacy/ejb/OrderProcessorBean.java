package com.acme.legacy.ejb;

import com.acme.legacy.cdi.OrderPlacedEvent;
import com.acme.legacy.entity.Order;

import javax.ejb.Stateless;
import javax.ejb.TransactionAttribute;
import javax.ejb.TransactionAttributeType;
import javax.enterprise.event.Event;
import javax.inject.Inject;
import javax.persistence.EntityManager;
import javax.persistence.PersistenceContext;

@Stateless
public class OrderProcessorBean {

    @PersistenceContext(unitName = "OrderManagementPU")
    private EntityManager entityManager;

    @Inject
    private Event<OrderPlacedEvent> orderPlacedEvent;

    @TransactionAttribute(TransactionAttributeType.REQUIRED)
    public Order placeOrder(Order order) {
        entityManager.persist(order);
        orderPlacedEvent.fire(new OrderPlacedEvent(order.getId()));
        return order;
    }
}
