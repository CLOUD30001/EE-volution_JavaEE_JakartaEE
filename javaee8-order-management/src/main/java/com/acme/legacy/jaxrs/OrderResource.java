package com.acme.legacy.jaxrs;

import com.acme.legacy.ejb.OrderProcessorBean;
import com.acme.legacy.entity.Order;

import javax.ejb.EJB;
import javax.enterprise.context.RequestScoped;
import javax.validation.Valid;
import javax.ws.rs.Consumes;
import javax.ws.rs.GET;
import javax.ws.rs.POST;
import javax.ws.rs.Path;
import javax.ws.rs.PathParam;
import javax.ws.rs.Produces;
import javax.ws.rs.core.MediaType;
import javax.ws.rs.core.Response;

/**
 * Needs a CDI scope annotation (not just @Path) for the container to process the
 * @EJB field injection below - under beans.xml's bean-discovery-mode="annotated",
 * a plain JAX-RS resource with no CDI bean-defining annotation is invisible to CDI
 * and its @EJB/@Inject/@Resource fields are silently never populated.
 */
@Path("/orders")
@RequestScoped
public class OrderResource {

    @EJB
    private OrderProcessorBean orderProcessorBean;

    @POST
    @Consumes(MediaType.APPLICATION_JSON)
    @Produces(MediaType.APPLICATION_JSON)
    public Response createOrder(@Valid Order order) {
        Order saved = orderProcessorBean.placeOrder(order);
        return Response.status(Response.Status.CREATED).entity(saved).build();
    }

    @GET
    @Path("/{id}")
    @Produces(MediaType.APPLICATION_JSON)
    public Response getOrder(@PathParam("id") Long id) {
        return Response.ok().build();
    }
}
