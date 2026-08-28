package com.acme.legacy.ejb;

import javax.ejb.ActivationConfigProperty;
import javax.ejb.MessageDriven;
import javax.jms.JMSException;
import javax.jms.Message;
import javax.jms.MessageListener;
import javax.jms.TextMessage;

@MessageDriven(mappedName = "jms/OrderQueue", activationConfig = {
        // Note: the property VALUE is itself a javax.* string literal, separate
        // from any import - another case a pure import-scanner would miss.
        @ActivationConfigProperty(propertyName = "destinationType", propertyValue = "javax.jms.Queue")
})
public class OrderNotifierBean implements MessageListener {

    @Override
    public void onMessage(Message message) {
        try {
            if (message instanceof TextMessage) {
                String body = ((TextMessage) message).getText();
                System.out.println("Order notification received: " + body);
            }
        } catch (JMSException e) {
            throw new RuntimeException("Failed to process order notification", e);
        }
    }
}
