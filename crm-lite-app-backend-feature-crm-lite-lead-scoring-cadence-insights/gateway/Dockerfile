# syntax=docker/dockerfile:1
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /build
COPY pom.xml ./
RUN mvn -q -B dependency:go-offline
COPY src ./src
RUN mvn -q -B package -DskipTests

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=build /build/target/crm-lite-gateway-*.jar ./app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
