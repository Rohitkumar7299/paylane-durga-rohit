output "instance_id" {

  value = aws_instance.paylane.id
}



output "public_ip" {

  value = aws_instance.paylane.public_ip
}



output "public_dns" {

  value = aws_instance.paylane.public_dns
}
