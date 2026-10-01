package com.tachyon.crmlite.gateway.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Binds the {@code gateway.*} tree in application.yml. */
@ConfigurationProperties(prefix = "gateway")
public class GatewayProperties {

    private Headers headers = new Headers();
    private Jwt jwt = new Jwt();

    public Headers getHeaders() {
        return headers;
    }

    public void setHeaders(Headers headers) {
        this.headers = headers;
    }

    public Jwt getJwt() {
        return jwt;
    }

    public void setJwt(Jwt jwt) {
        this.jwt = jwt;
    }

    /** Header names the backend trusts as gateway-forwarded identity — must
     * match its GATEWAY_EMPLOYEE_HEADER / GATEWAY_ROLES_HEADER settings. */
    public static class Headers {
        private String employeeId;
        private String roles;

        public String getEmployeeId() {
            return employeeId;
        }

        public void setEmployeeId(String employeeId) {
            this.employeeId = employeeId;
        }

        public String getRoles() {
            return roles;
        }

        public void setRoles(String roles) {
            this.roles = roles;
        }
    }

    /** HMAC secret this gateway uses to verify the Authorization: Bearer JWT. */
    public static class Jwt {
        private String secret;

        public String getSecret() {
            return secret;
        }

        public void setSecret(String secret) {
            this.secret = secret;
        }
    }
}
