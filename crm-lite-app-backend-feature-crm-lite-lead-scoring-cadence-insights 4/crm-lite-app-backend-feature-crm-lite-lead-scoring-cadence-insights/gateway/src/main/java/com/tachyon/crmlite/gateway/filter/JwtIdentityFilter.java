package com.tachyon.crmlite.gateway.filter;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.stream.Collectors;

import javax.crypto.SecretKey;

import com.tachyon.crmlite.gateway.config.GatewayProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Stateless bearer-token pass-through: no login, no session. Every proxied
 * request either carries a valid {@code Authorization: Bearer <jwt>} whose
 * claims become the trusted identity headers, or it doesn't and is forwarded
 * with none — the backend's own auth dependency (src/utils/security.py) is
 * what turns a missing identity into a 401/403.
 * <p>
 * Expected claims: {@code employee_id} (string — the backend's employee UUID)
 * and {@code roles} (a JSON array of role codes, or a comma-separated
 * string). Any X-Employee-Id/X-Roles the caller sent itself is always
 * stripped first — the backend trusts those headers unconditionally, so
 * letting a caller set them directly would be an impersonation hole.
 */
@Component
public class JwtIdentityFilter implements GlobalFilter, Ordered {

    private static final String EMPLOYEE_CLAIM = "employee_id";
    private static final String ROLES_CLAIM = "roles";
    private static final String BEARER_PREFIX = "Bearer ";

    private final GatewayProperties properties;
    private final SecretKey signingKey;

    public JwtIdentityFilter(GatewayProperties properties) {
        this.properties = properties;
        this.signingKey = Keys.hmacShaKeyFor(properties.getJwt().getSecret().getBytes(StandardCharsets.UTF_8));
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String authHeader = exchange.getRequest().getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
        if (authHeader == null || !authHeader.startsWith(BEARER_PREFIX)) {
            return chain.filter(exchange.mutate().request(stripIdentityHeaders(exchange)).build());
        }

        String token = authHeader.substring(BEARER_PREFIX.length());
        Claims claims;
        try {
            claims = Jwts.parser().verifyWith(signingKey).build().parseSignedClaims(token).getPayload();
        } catch (JwtException | IllegalArgumentException ex) {
            return rejectInvalidToken(exchange);
        }

        String employeeId = claims.get(EMPLOYEE_CLAIM, String.class);
        String roles = rolesToHeaderValue(claims.get(ROLES_CLAIM, Object.class));

        ServerHttpRequest request = exchange.getRequest().mutate()
                .headers(headers -> {
                    headers.remove(properties.getHeaders().getEmployeeId());
                    headers.remove(properties.getHeaders().getRoles());
                    if (employeeId != null && !employeeId.isBlank()) {
                        headers.set(properties.getHeaders().getEmployeeId(), employeeId);
                    }
                    if (roles != null && !roles.isBlank()) {
                        headers.set(properties.getHeaders().getRoles(), roles);
                    }
                })
                .build();
        return chain.filter(exchange.mutate().request(request).build());
    }

    private ServerHttpRequest stripIdentityHeaders(ServerWebExchange exchange) {
        return exchange.getRequest().mutate()
                .headers(headers -> {
                    headers.remove(properties.getHeaders().getEmployeeId());
                    headers.remove(properties.getHeaders().getRoles());
                })
                .build();
    }

    private String rolesToHeaderValue(Object rawRoles) {
        if (rawRoles == null) {
            return "";
        }
        if (rawRoles instanceof List<?> list) {
            return list.stream().map(String::valueOf).collect(Collectors.joining(","));
        }
        return String.valueOf(rawRoles);
    }

    private Mono<Void> rejectInvalidToken(ServerWebExchange exchange) {
        exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
        exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
        byte[] body = ("{\"error\":{\"code\":\"INVALID_TOKEN\",\"message\":"
                + "\"The bearer token is missing required claims, malformed, or has an invalid signature.\"}}")
                .getBytes(StandardCharsets.UTF_8);
        DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(body);
        return exchange.getResponse().writeWith(Mono.just(buffer));
    }

    @Override
    public int getOrder() {
        // Early: must run before NettyRoutingFilter (Ordered.MAX_VALUE) sends
        // the request on.
        return Ordered.HIGHEST_PRECEDENCE + 10;
    }
}
