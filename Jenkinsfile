pipeline {
    agent any

    environment {
        REGISTRY = 'ghcr.io'
        OWNER = 'rohitkumar7299'
        GHCR = credentials('ghcr-creds')
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Lint') {
            steps {
                sh '''
                    python3 -m pip install --break-system-packages ruff==0.15.21

                    ~/.local/bin/ruff check \
                    services/payment-svc/app \
                    services/mandate-svc/app \
                    services/ledger-svc/app \
                    services/settlement-worker/worker.py
                '''
            }
        }

        stage('Login to GHCR') {
            steps {
                sh '''
                    echo $GHCR_PSW | docker login ghcr.io \
                    -u $GHCR_USR \
                    --password-stdin
                '''
            }
        }

        stage('Build and Push Images') {
            steps {
                script {

                    def services = [
                        'payment-svc',
                        'mandate-svc',
                        'ledger-svc',
                        'settlement-worker',
                        'portal'
                    ]

                    services.each { svc ->

                        def image = "${REGISTRY}/${OWNER}/paylane-${svc}"

                        sh """
                            docker build \
                                -t ${image}:${env.BUILD_NUMBER} \
                                -t ${image}:latest \
                                services/${svc}

                            docker push ${image}:${env.BUILD_NUMBER}

                            docker push ${image}:latest
                        """
                    }
                }
            }
        }
    }

    post {
        always {
            sh 'docker logout ghcr.io || true'
        }
    }
}
