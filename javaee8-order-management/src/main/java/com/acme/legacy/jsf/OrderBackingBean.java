package com.acme.legacy.jsf;

import com.acme.legacy.ejb.OrderProcessorBean;
import com.acme.legacy.entity.Order;

import javax.ejb.EJB;
import javax.faces.view.ViewScoped;
import javax.inject.Named;
import java.io.Serializable;

@Named
@ViewScoped
public class OrderBackingBean implements Serializable {

    @EJB
    private OrderProcessorBean orderProcessorBean;

    private Order currentOrder = new Order();

    public String submitOrder() {
        orderProcessorBean.placeOrder(currentOrder);
        return "confirmation";
    }

    public Order getCurrentOrder() {
        return currentOrder;
    }
}
