package com.tachyon.crmlite.gateway.filter;

import java.util.UUID;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Mirrors the backend's own RequestContextMiddleware: reuse an incoming
 * X-Request-Id, or mint one, so a request can be traced across gateway ->
 * backend -> logs regardless of which side originated the id.
 */
@Component
public class CorrelationIdFilter implements GlobalFilter, Ordered {

    private static final String HEADER = "X-Request-Id";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String requestId = exchange.getRequest().getHeaders().getFirst(HEADER);
        if (requestId == null || requestId.isBlank()) {
            requestId = UUID.randomUUID().toString();
        }
        String finalRequestId = requestId;
        ServerHttpRequest request = exchange.getRequest().mutate()
                .headers(headers -> headers.set(HEADER, finalRequestId))
                .build();
        exchange.getResponse().getHeaders().set(HEADER, finalRequestId);
        return chain.filter(exchange.mutate().request(request).build());
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }
}
